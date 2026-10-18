#!/usr/bin/env python3
"""feishu-brain · 双向链接层

三层关系，可信度递减、覆盖度递增：
  L1 原生链接 —— 解析正文里作者手写的飞书文档链接，实测
  L2 知识回链 —— 由 knowledge.json 的 sources 反查，由 build_html 处理
  L3 相似文档 —— 关键词 TF-IDF 余弦，标注为「推断」

用法:
  python3 links.py --raw raw --inventory index/inventory.json --out index/links.json
"""
import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

# 只认 token，不认域名：www.feishu.cn / <tenant>.feishu.cn / larksuite.com 同 token
LINK_RE = re.compile(
    r"https?://[a-z0-9.\-]*(?:feishu\.cn|larksuite\.com)/"
    r"(?:docx|wiki|sheets|base|docs|mindnotes|slides)/([A-Za-z0-9]{6,})"
)
SIM_TOP = 5
COMMON_TERM_CAP = 80   # 出现超过这么多篇的词不再用于找相似（区分度太低）


def build_similar(terms, tok_index):
    """倒排 + 只比较共享词的文档对，避免 N² 全量。"""
    postings = defaultdict(list)
    for tok, ws in terms.items():
        for w in ws:
            postings[w].append(tok)

    pair = Counter()
    for w, toks in postings.items():
        if len(toks) < 2 or len(toks) > COMMON_TERM_CAP:
            continue
        idf = math.log(len(terms) / len(toks) + 1)
        for i in range(len(toks)):
            for j in range(i + 1, len(toks)):
                a, b = toks[i], toks[j]
                pair[(a, b) if a < b else (b, a)] += idf

    best = defaultdict(list)
    for (a, b), score in pair.items():
        if score < 1.0:
            continue
        best[a].append((b, score))
        best[b].append((a, score))

    out = {}
    for tok, lst in best.items():
        lst.sort(key=lambda x: -x[1])
        top = lst[:SIM_TOP]
        mx = top[0][1] if top else 1
        out[tok] = [[t, round(s / mx, 2)] for t, s in top]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="raw")
    ap.add_argument("--inventory", default="index/inventory.json")
    ap.add_argument("--out", default="index/links.json")
    ap.add_argument("--no-similar", action="store_true", help="跳过相似度计算（大语料可关）")
    args = ap.parse_args()

    raw = Path(args.raw)
    inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    docs = inv["docs"]
    terms = inv.get("terms", {})

    # node_token → obj_token（wiki 链接用的是 node_token）
    node2obj = {}
    for d in docs:
        if d.get("node_token"):
            node2obj[d["node_token"]] = d["token"]
    known = {d["token"] for d in docs}

    outlinks = defaultdict(set)
    unresolved = Counter()
    for d in docs:
        p = raw / "docs" / f"{d['token']}.txt"
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for mt in LINK_RE.finditer(text):
            t = mt.group(1)
            t = node2obj.get(t, t)
            if t == d["token"]:
                continue
            if t in known:
                outlinks[d["token"]].add(t)
            else:
                unresolved[t] += 1

    backlinks = defaultdict(set)
    for src, dsts in outlinks.items():
        for t in dsts:
            backlinks[t].add(src)

    similar = {} if args.no_similar else build_similar(terms, known)

    edges = sum(len(v) for v in outlinks.values())
    linked = len(outlinks)
    result = {
        "stats": {
            "docs": len(docs),
            "docs_with_outlink": linked,
            "coverage": round(linked / len(docs) * 100, 1) if docs else 0,
            "edges": edges,
            "avg_out": round(edges / linked, 2) if linked else 0,
            "unresolved_tokens": len(unresolved),
            "similar_pairs": sum(len(v) for v in similar.values()) // 2,
        },
        "outlinks": {k: sorted(v) for k, v in outlinks.items()},
        "backlinks": {k: sorted(v) for k, v in backlinks.items()},
        "similar": similar,
        "legend": {
            "outlinks/backlinks": "L1 实测：作者在正文里手写的链接",
            "similar": "L3 推断：关键词相似度，非作者建立",
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

    s = result["stats"]
    print(f"L1 原生链接：{s['docs_with_outlink']} 篇有出链（{s['coverage']}%），"
          f"{s['edges']} 条边，篇均 {s['avg_out']}；指向未知文档 {s['unresolved_tokens']} 个")
    print(f"L3 相似度：{s['similar_pairs']} 对（推断层）")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
