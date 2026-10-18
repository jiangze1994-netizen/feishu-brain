#!/usr/bin/env python3
"""feishu-brain · L3 提炼的原料准备

这个脚本不产出结论——结论必须由 AI 读真实片段后写。
它只负责把「一个集里的证据」压缩成 AI 能一次读完的材料包。

用法:
  python3 distill.py --raw raw --inventory index/inventory.json \
        --sets index/sets.json --set S01 --out index/distill-S01.md
  python3 distill.py --set all --out index/distill-all.md --budget 60000
"""
import argparse
import json
import re
from collections import Counter
from pathlib import Path

NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|万|亿|元|块|倍|人|篇|天|单|条|个|次|页|小时|分钟|pp)")
JUDGE_WORDS = ("必须", "应该", "不要", "不能", "建议", "原则", "结论", "原因", "因为",
               "导致", "说明", "意味着", "关键", "核心", "问题在于", "本质", "前提",
               "如果", "那么", "前提是", "底线", "红线", "优先级", "决定")
SENT_SPLIT = re.compile(r"(?<=[。！？；\n])")
HEAD_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.M)


def sentences(text):
    out = []
    for s in SENT_SPLIT.split(text):
        s = re.sub(r"\s+", " ", s).strip(" #*-—·")
        if 12 <= len(s) <= 130:
            out.append(s)
    return out


def pick_key_sentences(text, limit=8):
    cands = []
    for pos, s in enumerate(sentences(text)):
        score = 0
        if NUM_RE.search(s):
            score += 3
        score += sum(1 for w in JUDGE_WORDS if w in s)
        if re.match(r"^[-*\d]", s):
            score += 1
        if score >= 2:
            cands.append((score, pos, s))
    cands.sort(key=lambda x: (-x[0], x[1]))
    seen, out = set(), []
    for _, _, s in cands:
        key = s[:24]
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def outline(text, cap=12):
    hs = [(len(m.group(1)), m.group(2).strip()) for m in HEAD_RE.finditer(text)]
    hs = [(l, t) for l, t in hs if l <= 3][:cap]
    return [("  " * (l - 1)) + "- " + t for l, t in hs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="raw")
    ap.add_argument("--inventory", default="index/inventory.json")
    ap.add_argument("--sets", default="index/sets.json")
    ap.add_argument("--set", required=True, help="集号，如 S01；all 表示全部")
    ap.add_argument("--out", default="")
    ap.add_argument("--budget", type=int, default=40000, help="材料包总字数上限")
    ap.add_argument("--per-doc", type=int, default=8, help="每篇最多抽几句")
    args = ap.parse_args()

    raw = Path(args.raw)
    inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    sets_doc = json.loads(Path(args.sets).read_text(encoding="utf-8"))
    docmap = {d["token"]: d for d in inv["docs"]}

    if args.set == "all":
        targets = [d["token"] for d in inv["docs"] if d["status"] not in ("deny", "fail", "empty")]
        title = "全部语料"
    else:
        s = next((x for x in sets_doc.get("sets", []) if x["id"] == args.set), None)
        if not s:
            raise SystemExit(f"找不到集 {args.set}")
        targets = s.get("docs", [])
        title = f"{s['id']} {s.get('name','')}"

    # 优先顺序：证据可用 > 字数适中 > 较新
    targets = [t for t in targets if t in docmap]
    targets.sort(key=lambda t: (
        not docmap[t].get("evident"),
        abs(docmap[t].get("chars", 0) - 2500),
        -int((docmap[t].get("created") or "2000")[:4] or 2000 or 0) if (docmap[t].get("created") or "")[:4].isdigit() else 0,
    ))

    out = [f"# 证据材料包 · {title}", ""]
    out.append(f"> 候选文档 {len(targets)} 篇；本包按预算 {args.budget:,} 字截断。")
    out.append("> **读法**：先看下面的术语与数字，再逐篇读关键句。"
               "只把能在这份材料里找到依据的结论写进 knowledge.json，找不到的写「缺」。")
    out.append("")

    terms = Counter()
    for t in targets[:200]:
        for w in (inv.get("terms", {}).get(t) or []):
            terms[w] += 1
    if terms:
        out.append("**高频术语**：" + "、".join(w for w, _ in terms.most_common(20)))
        out.append("")

    used = sum(len(x) for x in out)
    shown = 0
    for t in targets:
        if used >= args.budget:
            break
        d = docmap[t]
        p = raw / "docs" / f"{t}.txt"
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        key = pick_key_sentences(text, args.per_doc)
        ol = outline(text)
        if not key and not ol:
            continue
        block = [f"### [{d['title']}]({d.get('url','')})"]
        block.append(f"`{d.get('created','')[:10]}` · {d.get('chars',0):,} 字 · "
                     f"{d.get('space','')} · {'证据可用' if d.get('evident') else '参考'}")
        if ol:
            block.append("")
            block.append("\n".join(ol))
        if key:
            block.append("")
            for s in key:
                block.append(f"- {s}")
        block.append("")
        body = "\n".join(block)
        if used + len(body) > args.budget:
            break
        out.extend(block)
        used += len(body)
        shown += 1

    out.append("---")
    out.append("")
    out.append(f"已收录 {shown}/{len(targets)} 篇。")
    out.append("")
    out.append("**下一步**：把提炼结果写成 `knowledge.json`，格式：")
    out.append("```json")
    out.append(json.dumps({
        "items": [{
            "id": f"{args.set if args.set!='all' else 'S01'}-K01",
            "set": args.set if args.set != "all" else "S01",
            "set_name": title,
            "title": "知识条目标题",
            "conclusion": "一句话结论（≤60 字）",
            "detail": "展开说明（可选，≤300 字）",
            "evidence": "A",
            "sources": ["原文 token，必须真实存在于本材料包"],
            "first_seen": "2024-03",
            "last_updated": "2026-09",
        }]
    }, ensure_ascii=False, indent=2))
    out.append("```")

    md = "\n".join(out)
    outp = Path(args.out or f"index/distill-{args.set}.md")
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(md, encoding="utf-8")
    print(f"材料包 {len(md):,} 字 / {shown} 篇 → {outp}")


if __name__ == "__main__":
    main()
