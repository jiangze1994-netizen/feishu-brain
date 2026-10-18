#!/usr/bin/env python3
"""feishu-brain · 回写飞书索引文档

生成一篇飞书文档作为「第二个入口」：同事点开就能看到整个大脑的目录。

幂等：首次创建后把 doc_token 记进 state.json，之后更新同一篇。
身份：必须 --as user，bot 创建的文档同事看不到。

用法:
  python3 index_doc.py --brain ~/.feishu-brain --dry-run    # 只生成 markdown，不写飞书
  python3 index_doc.py --brain ~/.feishu-brain --confirm    # 真正写入
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

MAX_CHARS = 20000


def read_json(p, default=None):
    p = Path(p)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def build_markdown(inv, sets_doc, knowledge, owner, unclassified_titles):
    m = inv["meta"]
    docs = {d["token"]: d for d in inv["docs"]}
    items = knowledge.get("items", []) if isinstance(knowledge, dict) else (knowledge or [])
    by_set = {}
    for k in items:
        by_set.setdefault(k.get("set", ""), []).append(k)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = []
    out.append(f"# {owner}的飞书知识大脑")
    out.append("")
    out.append(f"> 语料 {m['total_docs']:,} 篇 / {m['total_chars']:,} 字 / "
               f"证据可用 {m['evident_docs']:,} 篇（{m['evident_ratio']}%）")
    out.append(f"> 生成于 {now}，共 {len(sets_doc.get('sets', []))} 集")
    out.append("")
    out.append("## 这个大脑怎么用")
    out.append("")
    out.append("- 想知道某个主题下我掌握什么 → 按下面的集查")
    out.append("- 想找某篇原文 → 点表格里的「原文」直达飞书文档")
    out.append("- 想知道结论有多可靠 → 看「证据」列：A 原文明确 / B 多篇可推 / C 单一来源")
    out.append("")
    out.append("## 集目录")
    out.append("")

    budget = MAX_CHARS - len("".join(out))
    for s in sets_doc.get("sets", []):
        covered = [d for d in inv["docs"] if d["token"] in set(s.get("docs", []))]
        chars = sum(d["chars"] for d in covered)
        ev = sum(1 for d in covered if d.get("evident"))
        block = [f"### {s.get('id','')} {s.get('name','')}"]
        block.append("")
        block.append(f"> 覆盖 {len(covered):,} 篇 / {chars:,} 字 ｜ "
                     f"证据可用 {ev} 篇 ｜ 已提炼 {len(by_set.get(s.get('id',''), []))} 条")
        if s.get("desc"):
            block.append(f"> {s['desc']}")
        block.append("")
        ks = by_set.get(s.get("id", ""), [])
        if ks:
            block.append("| 知识条目 | 一句话结论 | 证据 | 原文 |")
            block.append("|---|---|---|---|")
            for k in ks[:40]:
                srcs = k.get("sources", [])
                first = docs.get(srcs[0]) if srcs else None
                link = f"[原文]({first['url']})" if first and first.get("url") else "—"
                concl = (k.get("conclusion") or "").replace("|", "｜")[:90]
                block.append(f"| {k.get('title','').replace('|','｜')} | {concl} | "
                             f"{k.get('evidence','')} | {link} |")
        else:
            # 未提炼时给出该集最大的几篇，至少可导航
            top = sorted(covered, key=lambda d: -d["chars"])[:12]
            block.append("| 主要文档 | 字数 | 原文 |")
            block.append("|---|---|---|")
            for d in top:
                block.append(f"| {d['title'].replace('|','｜')[:44]} | {d['chars']:,} | "
                             f"[链接]({d.get('url','')}) |")
        block.append("")
        need = len("\n".join(block))
        if budget - need < 1500:
            out.append("")
            out.append("> 篇幅已达上限，其余集请在本地 HTML 里查看。")
            break
        out.extend(block)
        budget -= need

    if unclassified_titles:
        out.append("## 未分类文档")
        out.append("")
        out.append(f"{len(unclassified_titles):,} 篇，未归入任何集（多为空壳、无权限或极短文档）：")
        out.append("")
        for t, tok in unclassified_titles[:30]:
            out.append(f"- {t}")
        if len(unclassified_titles) > 30:
            out.append(f"- …另 {len(unclassified_titles)-30} 篇，见本地 HTML")
        out.append("")

    out.append("---")
    out.append("")
    out.append("_本页由 feishu-brain 自动生成，重复运行会更新同一篇，不会新建副本。_")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--brain", default=".")
    ap.add_argument("--owner", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--confirm", action="store_true", help="真正写入飞书（写操作）")
    ap.add_argument("--parent-position", default="my_library",
                    help="创建位置，默认 my_library（我的文档库根目录）")
    args = ap.parse_args()

    brain = Path(args.brain).expanduser()
    idx = brain / "index"
    inv = read_json(idx / "inventory.json")
    if not inv:
        raise SystemExit("找不到 inventory.json，先跑 L1 体检")
    sets_doc = read_json(idx / "sets.json", {"sets": [], "unclassified": []})
    knowledge = read_json(idx / "knowledge.json", {"items": []})
    state = read_json(brain / "state.json", {}) or {}

    owner = args.owner or state.get("owner") or "我"
    docs = {d["token"]: d for d in inv["docs"]}
    unc = [(docs[t]["title"], t) for t in sets_doc.get("unclassified", []) if t in docs]

    md = build_markdown(inv, sets_doc, knowledge, owner, unc)
    md_path = idx / "索引文档.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"markdown {len(md):,} 字 → {md_path}")

    if args.dry_run or not args.confirm:
        print("（未写入飞书。确认后加 --confirm 才会创建/更新文档）")
        print("预览前 40 行：")
        print("\n".join(md.splitlines()[:40]))
        return

    token = state.get("index_doc_token", "")
    if token:
        cmd = ["lark-cli", "docs", "+update", "--doc", token, "--command", "overwrite",
               "--doc-format", "markdown", "--content", f"@{md_path}", "--as", "user",
               "--format", "json"]
        action = "更新"
    else:
        cmd = ["lark-cli", "docs", "+create", "--content", f"@{md_path}",
               "--doc-format", "markdown", "--parent-position", args.parent_position,
               "--as", "user", "--format", "json"]
        action = "创建"

    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr[-600:] + "\n")
        raise SystemExit(f"{action}索引文档失败")

    try:
        d = json.loads(p.stdout)
    except Exception:
        print(p.stdout[:500])
        raise SystemExit("返回不是 JSON，请人工核对")

    data = d.get("data", {}) or {}
    doc = data.get("document", {}) or data
    new_token = (doc.get("document_id") or doc.get("token") or doc.get("obj_token")
                 or data.get("document_id") or "")
    url = doc.get("url") or data.get("url") or ""

    if new_token:
        state["index_doc_token"] = new_token
        state["index_doc_url"] = url
        (brain / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"✅ 已{action}索引文档：{url or new_token}")
    print("再次运行会更新同一篇，不会新建。")


if __name__ == "__main__":
    main()
