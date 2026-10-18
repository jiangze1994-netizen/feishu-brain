#!/usr/bin/env python3
"""feishu-brain · 检索层（给 AI 用，不是给人看）

在本地语料里做关键词检索，输出 markdown 表，供 AI 据此回答并标注出处。

不用向量、不联网、不依赖任何第三方包。

用法:
  python3 search.py --query "转化率 目标" --top 15
  python3 search.py --query "周报" --set S01 --since 2025-01-01
  python3 search.py --query "ecpm" --format json
"""
import argparse
import json
import math
import re
from pathlib import Path

SNIPPET = 90


def load_sets(path):
    p = Path(path)
    if not p.exists():
        return {}, []
    d = json.loads(p.read_text(encoding="utf-8"))
    m = {}
    for s in d.get("sets", []):
        for t in s.get("docs", []):
            m[t] = s
    return m, d.get("sets", [])


def make_snippet(text, words, width=SNIPPET):
    """在正文里找第一个命中位置，截一段。"""
    low = text.lower()
    pos = -1
    for w in words:
        i = low.find(w.lower())
        if i >= 0 and (pos < 0 or i < pos):
            pos = i
    if pos < 0:
        return ""
    start = max(0, pos - width // 2)
    end = min(len(text), pos + width)
    frag = re.sub(r"\s+", " ", text[start:end]).strip()
    return ("…" if start > 0 else "") + frag + ("…" if end < len(text) else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="raw")
    ap.add_argument("--inventory", default="index/inventory.json")
    ap.add_argument("--sets", default="index/sets.json")
    ap.add_argument("--query", required=True)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--set", default="")
    ap.add_argument("--since", default="")
    ap.add_argument("--type", default="")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    args = ap.parse_args()

    words = [w for w in re.split(r"\s+", args.query.strip()) if w]
    if not words:
        raise SystemExit("query 为空")

    raw = Path(args.raw)
    inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    docs = inv["docs"]
    set_of, _ = load_sets(args.sets)

    # 先按元数据过滤
    pool = []
    for d in docs:
        if args.since and (d.get("created") or "9999") < args.since:
            continue
        if args.type and d.get("type") != args.type:
            continue
        if args.set:
            s = set_of.get(d["token"])
            if not s or s.get("id") != args.set:
                continue
        pool.append(d)

    hits = []
    for d in pool:
        title = d.get("title") or ""
        p = raw / "docs" / f"{d['token']}.txt"
        text = ""
        if p.exists():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
        if not text and not title:
            continue
        low_t, low_x = title.lower(), text.lower()

        score, matched = 0.0, 0
        for w in words:
            lw = w.lower()
            n_title = low_t.count(lw)
            n_body = low_x.count(lw)
            if n_title == 0 and n_body == 0:
                continue
            matched += 1
            score += n_title * 10 + (math.log1p(n_body) * 3 if n_body else 0)
        if matched == 0:
            continue
        if matched == len(words):          # 全词命中加权
            score += 15
        score /= 1 + math.log1p(max(d.get("chars", 0), 1)) / 10   # 轻微抑制超长文

        hits.append({
            "token": d["token"],
            "title": title,
            "date": d.get("created") or d.get("modified") or "",
            "year": d.get("year", ""),
            "type": d.get("type", ""),
            "space": d.get("space", ""),
            "chars": d.get("chars", 0),
            "set": (set_of.get(d["token"]) or {}).get("id", ""),
            "set_name": (set_of.get(d["token"]) or {}).get("name", ""),
            "url": d.get("url", ""),
            "score": round(score, 2),
            "matched": matched,
            "snippet": make_snippet(text, words),
        })

    hits.sort(key=lambda x: (-x["matched"], -x["score"]))
    hits = hits[: args.top]

    if args.format == "json":
        print(json.dumps({"query": args.query, "count": len(hits), "results": hits},
                         ensure_ascii=False, indent=1))
        return

    if not hits:
        print(f"未命中：`{args.query}`\n\n语料里没有找到相关内容。**不要编造答案**，"
              f"直接告诉用户「你的飞书文档里查不到这个」，并建议换关键词或确认文档是否在权限范围内。")
        return

    print(f"命中 {len(hits)} 篇（按全词命中数 + 相关度排序）\n")
    print("| 得分 | 标题 | 日期 | 集 | 字数 | 命中片段 | 原文 |")
    print("|---|---|---|---|---|---|---|")
    for h in hits:
        title = (h["title"] or "(无标题)").replace("|", "｜")[:40]
        snip = (h["snippet"] or "").replace("|", "｜")[:80]
        sn = f"{h['set']} {h['set_name']}".strip() or "—"
        print(f"| {h['score']} | {title} | {h['date']} | {sn} | {h['chars']} | {snip} | [链接]({h['url']}) |")

    print(f"\n---\n引用时请标注：标题 + 日期 + 链接。片段只是节选，"
          f"下结论前建议打开原文核对关键数字。")


if __name__ == "__main__":
    main()
