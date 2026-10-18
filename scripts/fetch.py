#!/usr/bin/env python3
"""feishu-brain · 拉取层

发现用户有权限的全部飞书文档，抓成本地纯文本。

发现层三路（缺一路就会系统性漏文档）：
  1. wiki 知识空间树（含 my_library 个人文档库）
  2. Drive 云空间文件夹树（根目录 + 逐层递归）
  3. docs +search 补充（可选，按关键词）

只依赖 lark-cli + Python 标准库。

用法:
  python3 fetch.py --out raw                  # 发现 + 抓取（默认）
  python3 fetch.py --out raw --stage discover # 只发现，不抓正文
  python3 fetch.py --out raw --limit 100      # 只处理前 100 篇（测试）
  python3 fetch.py --out raw --since 2025-01-01
  python3 fetch.py --out raw --space 商业化拓客
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

DOC_TYPES = {"docx", "doc", "mindnote", "slides"}
SKIP_TYPES = {"folder", "shortcut"}
BODY_MAX = 200_000  # 单篇正文上限，防超长文档撑爆


def cli(args, timeout=120, retries=1):
    last = None
    for i in range(retries):
        try:
            p = subprocess.run(["lark-cli"] + args, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            last = "timeout"
            time.sleep(1.5 * (i + 1))
            continue
        if p.returncode != 0:
            last = (p.stderr or p.stdout).strip()[:200]
            time.sleep(1.0 * (i + 1))
            continue
        try:
            return json.loads(p.stdout), None
        except Exception:
            last = "bad json: " + p.stdout[:120]
    return None, last


def ts_to_date(v):
    """飞书时间戳（秒或毫秒）→ YYYY-MM-DD"""
    if not v:
        return ""
    try:
        n = int(v)
        if n > 10_000_000_000:
            n //= 1000
        return datetime.fromtimestamp(n, tz=timezone.utc).astimezone().strftime("%Y-%m-%d")
    except Exception:
        return str(v)[:10]


# ---------------- 发现层 ----------------

def discover_spaces():
    """全部可访问的 wiki 空间，含 my_library。"""
    out = []
    d, err = cli(["wiki", "+space-list", "--page-all", "--page-limit", "0",
                  "--page-size", "50", "--format", "json"], retries=2)
    if d:
        for s in d.get("data", {}).get("spaces", []):
            out.append({"space_id": s["space_id"], "name": s.get("name") or "(未命名空间)"})
    else:
        sys.stderr.write(f"[warn] space-list 失败: {err}\n")
    # +space-list 不返回个人文档库，单独补
    if not any(s["space_id"] == "my_library" for s in out):
        out.append({"space_id": "my_library", "name": "我的文档库"})
    return out


def walk_wiki_space(space_id, space_name, max_depth, node_cap):
    """BFS 遍历一个知识空间的所有节点。"""
    found = []
    seen = set()
    queue = [(None, 0)]
    while queue and len(found) < node_cap:
        parent, depth = queue.pop(0)
        args = ["wiki", "+node-list", "--space-id", space_id,
                "--page-size", "50", "--page-all", "--page-limit", "0", "--format", "json"]
        if parent:
            args += ["--parent-node-token", parent]
        d, err = cli(args, retries=2)
        if not d:
            sys.stderr.write(f"[warn] {space_name}/{parent or 'root'} 节点列举失败: {err}\n")
            continue
        for it in d.get("data", {}).get("nodes", []) or []:
            nt = it.get("node_token")
            if not nt or nt in seen:
                continue
            seen.add(nt)
            found.append({
                "token": it.get("obj_token") or nt,
                "node_token": nt,
                "title": (it.get("title") or "").strip(),
                "type": it.get("obj_type") or "",
                "space": space_name,
                "path": it.get("title") or "",
                "created": "",
                "modified": "",
                "source": "wiki",
                "has_child": bool(it.get("has_child")),
                "depth": depth,
            })
            if it.get("has_child") and depth + 1 < max_depth and len(found) < node_cap:
                queue.append((nt, depth + 1))
    return found


def walk_drive(max_depth, dir_cap, domain_box):
    """BFS 遍历云空间文件夹树。"""
    found = []
    seen_dirs = set()
    queue = [("", "", 0)]
    dirs = 0
    while queue and dirs < dir_cap:
        ftok, path, depth = queue.pop(0)
        if ftok in seen_dirs:
            continue
        seen_dirs.add(ftok)
        dirs += 1
        page_token = None
        for _ in range(40):
            params = {"folder_token": ftok, "page_size": 200}
            if page_token:
                params["page_token"] = page_token
            d, err = cli(["drive", "files", "list", "--params", json.dumps(params),
                          "--format", "json"], retries=2)
            if not d:
                sys.stderr.write(f"[warn] drive {path or '/'} 列举失败: {err}\n")
                break
            data = d.get("data", {}) or {}
            if not domain_box.get("domain"):
                # 从任一 url 反推租户域名
                for f in (data.get("files") or []):
                    m = re.match(r"(https://[^/]+)", f.get("url") or "")
                    if m:
                        domain_box["domain"] = m.group(1)
                        break
            for f in data.get("files") or []:
                typ = f.get("type") or ""
                if typ in SKIP_TYPES:
                    if typ == "folder" and depth + 1 <= max_depth:
                        queue.append((f.get("token"), (path + "/" + (f.get("name") or "")).strip("/"), depth + 1))
                    continue
                found.append({
                    "token": f.get("token"),
                    "node_token": "",
                    "title": (f.get("name") or "").strip(),
                    "type": typ,
                    "space": "云空间",
                    "path": (path + "/" + (f.get("name") or "")).strip("/"),
                    "created": ts_to_date(f.get("created_time")),
                    "modified": ts_to_date(f.get("modified_time")),
                    "source": "drive",
                    "has_child": False,
                    "depth": depth,
                    "url": f.get("url") or "",
                })
            if not data.get("has_more"):
                break
            nxt = data.get("next_page_token")
            if not nxt:
                break
            page_token = nxt
    return found


def build_url(rec, domain):
    if rec.get("url"):
        return rec["url"]
    tok = rec.get("node_token") or rec.get("token")
    if not tok or not domain:
        return ""
    kind = rec.get("type") or "docx"
    if rec.get("node_token") and rec.get("source") == "wiki":
        return f"{domain}/wiki/{rec['node_token']}"
    seg = {"docx": "docx", "doc": "docs", "sheet": "sheets",
           "bitable": "base", "mindnote": "mindnotes", "slides": "slides"}.get(kind, "file")
    return f"{domain}/{seg}/{tok}"


# ---------------- 抓取层 ----------------

def fetch_body(token, url, out_dir):
    """取单篇正文 markdown。"""
    path = out_dir / f"{token}.txt"
    if path.exists() and path.stat().st_size > 20:
        return "skip", path
    for attempt in range(3):
        d, err = cli(["docs", "+fetch", "--doc", url or token,
                      "--doc-format", "markdown", "--format", "json"], timeout=150)
        if d:
            c = d.get("data", {}).get("document", {}).get("content")
            if c is None:
                c = d.get("data", {}).get("content")
            if c is not None:
                c = re.sub(r"\n{3,}", "\n\n", c)[:BODY_MAX]
                path.write_text(c, encoding="utf-8")
                return "ok", path
            return "empty", None
        err = err or ""
        if any(k in err.lower() for k in ("permission", "forbidden", "not exist", "no access")):
            return "deny:" + err[:100], None
        time.sleep(1.5 * (attempt + 1))
    return "fail:" + (err or "")[:120], None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="raw")
    ap.add_argument("--stage", choices=["discover", "fetch", "all"], default="all")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--since", default="")
    ap.add_argument("--space", default="")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-depth", type=int, default=8)
    ap.add_argument("--node-cap", type=int, default=20000)
    ap.add_argument("--dir-cap", type=int, default=2000)
    args = ap.parse_args()

    out = Path(args.out)
    docs_dir = out / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    # ---- 发现 ----
    t0 = time.time()
    records, seen = [], set()
    domain_box = {}

    spaces = discover_spaces()
    sys.stderr.write(f"[discover] {len(spaces)} 个空间\n")
    for sp in spaces:
        if args.space and args.space not in sp["name"]:
            continue
        got = walk_wiki_space(sp["space_id"], sp["name"], args.max_depth, args.node_cap)
        for r in got:
            if r["token"] in seen:
                continue
            seen.add(r["token"])
            records.append(r)
        sys.stderr.write(f"[discover] {sp['name']}: {len(got)} 节点（累计 {len(records)}）\n")

    if not args.space:
        drive = walk_drive(args.max_depth, args.dir_cap, domain_box)
        for r in drive:
            if r["token"] in seen:
                continue
            seen.add(r["token"])
            records.append(r)
        sys.stderr.write(f"[discover] 云空间: {len(drive)} 项（累计 {len(records)}）\n")

    domain = domain_box.get("domain", "")
    for r in records:
        r["url"] = build_url(r, domain)
        r["chars"] = 0
        r["status"] = "pending"

    if args.since:
        records = [r for r in records if (r.get("created") or "9999") >= args.since]

    manifest_path = out / "manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    sys.stderr.write(f"[discover] 合计 {len(records)} 篇 → {manifest_path}  ({time.time()-t0:.0f}s)\n")

    if args.stage == "discover":
        by_type = {}
        for r in records:
            by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        print(json.dumps({"total": len(records), "by_type": by_type, "domain": domain},
                         ensure_ascii=False, indent=1))
        return

    # ---- 抓取 ----
    targets = [r for r in records if r["type"] in DOC_TYPES]
    if args.limit:
        targets = targets[:args.limit]
    skipped = [r for r in records if r["type"] not in DOC_TYPES]
    for r in skipped:
        r["status"] = "meta-only"

    sys.stderr.write(f"[fetch] 待抓 {len(targets)} 篇（跳过非文本类 {len(skipped)}）\n")
    stats = {}
    err_path = out / "errors.jsonl"
    with err_path.open("w", encoding="utf-8") as ef, ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_body, r["token"], r["url"], docs_dir): r for r in targets}
        done = 0
        for fut in futs:
            r = futs[fut]
            try:
                st, path = fut.result()
            except Exception as e:
                st, path = "fail:" + str(e)[:80], None
            key = st.split(":")[0]
            stats[key] = stats.get(key, 0) + 1
            r["status"] = key
            if path:
                r["chars"] = len(re.sub(r"\s", "", path.read_text(encoding="utf-8")))
            if key in ("deny", "fail", "empty"):
                ef.write(json.dumps({"token": r["token"], "title": r["title"],
                                     "url": r["url"], "reason": st}, ensure_ascii=False) + "\n")
            done += 1
            if done % 50 == 0:
                sys.stderr.write(f"[fetch] {done}/{len(targets)} {stats} {time.time()-t0:.0f}s\n")

    with manifest_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    total_chars = sum(r["chars"] for r in records)
    print(json.dumps({
        "total_docs": len(records),
        "fetched": stats.get("ok", 0) + stats.get("skip", 0),
        "by_status": stats,
        "meta_only": len(skipped),
        "total_chars": total_chars,
        "elapsed_s": round(time.time() - t0, 1),
        "manifest": str(manifest_path),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
