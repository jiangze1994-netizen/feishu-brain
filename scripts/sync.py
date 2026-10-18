#!/usr/bin/env python3
"""feishu-brain · 增量同步

发现层全量跑一遍，只抓「新增 / 有更新 / 本地缺失」的文档，然后重算索引。

设计取舍：对几百到几千篇的语料，全量发现（1–3 分钟）比维护一套增量发现更可靠——
增量搜索会系统性漏掉「别人新建、我首次获得权限」的文档。

用法:
  python3 sync.py --brain ~/.feishu-brain              # 增量
  python3 sync.py --brain ~/.feishu-brain --full       # 全量重抓
  python3 sync.py --brain ~/.feishu-brain --no-rebuild # 只同步，不重算索引
"""
import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fetch as F  # noqa: E402

DOC_TYPES = F.DOC_TYPES


def run_fetch_stage(raw, extra):
    cmd = [sys.executable, str(HERE / "fetch.py"), "--out", str(raw), "--stage", "discover"] + extra
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-800:] + "\n")
        raise SystemExit("发现层失败")
    return p.stderr


def load_state(p):
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"docs": {}, "updated_at": ""}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", default=".")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--no-rebuild", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    brain = Path(args.brain).expanduser()
    raw = brain / "raw"
    idx = brain / "index"
    idx.mkdir(parents=True, exist_ok=True)
    state_path = brain / "state.json"
    state = load_state(state_path)
    old_docs = state.get("docs", {})

    t0 = time.time()
    sys.stderr.write("[1/4] 发现层：全量遍历…\n")
    run_fetch_stage(raw, [])

    manifest = [json.loads(l) for l in (raw / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    new_manifest = {m["token"]: m for m in manifest if m.get("token")}

    # 判定待抓
    todo, kept, gone = [], 0, 0
    for tok, m in new_manifest.items():
        prev = old_docs.get(tok, {})
        fp = raw / "docs" / f"{tok}.txt"
        changed = (
            args.full
            or tok not in old_docs
            or not fp.exists()
            or (m.get("modified") and prev.get("modified") and m["modified"] > prev["modified"])
        )
        if m.get("type") not in DOC_TYPES:
            m["status"] = "meta-only"
            continue
        if changed:
            todo.append(m)
        else:
            m["status"] = prev.get("status", "ok")
            m["chars"] = prev.get("chars", 0)
            kept += 1
    gone = len([t for t in old_docs if t not in new_manifest])
    if args.limit:
        todo = todo[: args.limit]

    sys.stderr.write(f"[2/4] 待抓 {len(todo)} 篇（未变 {kept}，远端已消失 {gone}）\n")
    stats = {}
    errors = []
    if todo:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(F.fetch_body, m["token"], m.get("url", ""), raw / "docs"): m for m in todo}
            for fut in futs:
                m = futs[fut]
                try:
                    st, p = fut.result()
                except Exception as e:
                    st, p = "fail:" + str(e)[:80], None
                key = st.split(":")[0]
                stats[key] = stats.get(key, 0) + 1
                m["status"] = key
                m["chars"] = 0
                if p:
                    import re
                    m["chars"] = len(re.sub(r"\s", "", p.read_text(encoding="utf-8")))
                if key in ("deny", "fail", "empty"):
                    errors.append({"token": m["token"], "title": m.get("title"),
                                   "url": m.get("url"), "reason": st})

    # 写回 manifest（合并）
    with (raw / "manifest.jsonl").open("w", encoding="utf-8") as f:
        for m in manifest:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    with (raw / "errors.jsonl").open("w", encoding="utf-8") as ef:
        for e in errors:
            ef.write(json.dumps(e, ensure_ascii=False) + "\n")

    # 更新 state
    state["docs"] = {
        tok: {"modified": m.get("modified", ""), "status": m.get("status", ""),
              "chars": m.get("chars", 0), "title": m.get("title", "")}
        for tok, m in new_manifest.items()
    }
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    state["last_run"] = {"new": len(todo), "stats": stats, "gone": gone}
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    # 重建索引
    if not args.no_rebuild:
        sys.stderr.write("[3/4] 重算索引…\n")
        steps = [
            ["inventory.py", "--raw", str(raw), "--out", str(idx / "inventory.json")],
            ["links.py", "--raw", str(raw), "--inventory", str(idx / "inventory.json"),
             "--out", str(idx / "links.json")],
            ["build_html.py", "--index", str(idx), "--raw", str(raw),
             "--out", str(brain / "飞书知识大脑.html")],
        ]
        for s in steps:
            p = subprocess.run([sys.executable, str(HERE / s[0])] + s[1:], capture_output=True, text=True)
            if p.returncode != 0:
                sys.stderr.write(f"⚠️ {s[0]} 失败：{p.stderr[-400:]}\n")
            else:
                sys.stderr.write(f"  {s[0]} ok\n")

    sys.stderr.write("[4/4] 完成\n")
    print(json.dumps({
        "new_or_updated": len(todo),
        "unchanged": kept,
        "remote_gone": gone,
        "by_status": stats,
        "failed": len(errors),
        "elapsed_s": round(time.time() - t0, 1),
        "state": str(state_path),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
