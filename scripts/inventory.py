#!/usr/bin/env python3
"""feishu-brain · L1 体检层

读 raw/manifest.jsonl + raw/docs/*.txt，产出结构化盘点。

只依赖标准库。不修改任何源文件。

用法:
  python3 inventory.py --raw raw --out index/inventory.json
"""
import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

STOPWORDS = set("""
的 了 是 在 和 与 就 都 而 及 或 也 这 那 有 我 你 他 她 它 们 个 上 下 中 前 后
不 没 很 更 最 会 能 要 可以 需要 我们 你们 他们 一个 一些 什么 怎么 为什么 如何
如果 但是 因为 所以 而且 然后 已经 还是 就是 这个 那个 这些 那些 以及 通过 进行
文档 链接 内容 如下 以上 以下 备注 说明 情况 问题 相关 目前 现在 时间 日期
""".split())

NUM_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|万|亿|元|块|倍|人|篇|天|单|条|个|次|页|小时|分钟)")

# 用声明式/动作型章节判断"是否有结构"，不依赖任何行业词
STRUCT_RE = re.compile(r"^(?:#{1,4}\s|\s*[-*+]\s|\s*\d+\.\s|\|)", re.M)


HEAD_RE = re.compile(r"^#{1,4}\s+(.+?)\s*$", re.M)
BULLET_RE = re.compile(r"^\s*[-*]\s*([^\n：:，,。；;\s]{2,8})", re.M)
BAD_CHARS = set("的了着过并且但是如果因为所以该本这那其是在和与或把被将从对为")
# 文档结构词，不是主题词
GENERIC_EXACT = {
    "背景", "前言", "概述", "总览", "结论", "建议", "下一步", "待办", "附录", "参考",
    "目录", "目标", "现状", "原因", "措施", "结果", "过程", "其他", "备注", "补充",
    "问题", "总结", "复盘", "分析", "方案", "情况", "计划", "说明", "记录", "清单",
    "工作", "内容", "部分", "事项", "数据", "表格", "流程", "机制", "策略", "方法",
    "要点", "详情", "明细", "概览", "说明事项", "相关", "以上", "以下", "附件",
}
GENERIC_SUFFIX = ("分析", "方案", "情况", "总结", "复盘", "计划", "说明", "记录",
                  "清单", "问题", "工作", "内容", "部分", "事项", "流程", "机制")


def extract_terms(text, title, k=8):
    """用作者手写的章节标题/列表项/文档标题做特征词。

    这比全文 n-gram 可靠得多：小标题是人的显式标注，不会切出「价分」这种碎片。
    """
    raw = []
    for m in HEAD_RE.finditer(text[:20000]):
        raw.append(m.group(1))
    for m in BULLET_RE.finditer(text[:8000]):
        raw.append(m.group(1))
    if title:
        raw.append(title)

    out = []
    for s in raw:
        s = re.sub(r"[\s\d\W_]+", "", s)
        if not (2 <= len(s) <= 14) or s in GENERIC_EXACT:
            continue
        for suf in GENERIC_SUFFIX:
            if s.endswith(suf) and len(s) > len(suf) + 1:
                s = s[: -len(suf)]
                break
        if len(s) < 2 or s in GENERIC_EXACT or s in out:
            continue
        if any(ch in BAD_CHARS for ch in s):
            continue
        out.append(s)
        if len(out) >= k:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="raw")
    ap.add_argument("--out", default="index/inventory.json")
    ap.add_argument("--body-cap", type=int, default=20000,
                    help="单篇参与特征计算的最大字数")
    args = ap.parse_args()

    raw = Path(args.raw)
    manifest = raw / "manifest.jsonl"
    if not manifest.exists():
        raise SystemExit(f"找不到 {manifest}，先跑 fetch.py")

    docs, errors = [], []
    terms = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        tok = r.get("token")
        p = raw / "docs" / f"{tok}.txt"
        text = ""
        if p.exists():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
        chars = len(re.sub(r"\s", "", text))
        num_hits = len(NUM_RE.findall(text))
        rec = {
            "token": tok,
            "node_token": r.get("node_token", ""),
            "title": (r.get("title") or "").strip() or "(无标题)",
            "type": r.get("type", ""),
            "space": r.get("space", ""),
            "year": (r.get("created") or r.get("modified") or "")[:4] or "未知",
            "created": r.get("created", ""),
            "modified": r.get("modified", ""),
            "chars": chars,
            "url": r.get("url", ""),
            "status": r.get("status", ""),
            "has_number": num_hits >= 3,
            "num_hits": num_hits,
            "is_structured": bool(STRUCT_RE.search(text)),
            "is_meeting": any(w in (r.get("title") or "") for w in
                              ("纪要", "会议", "记录", "周会", "复盘", "沟通")),
        }
        # 证据可用：够长 + 有数字 + 有结构
        rec["evident"] = chars >= 300 and rec["has_number"] and rec["is_structured"]
        docs.append(rec)
        if text and chars >= 200:
            t = extract_terms(text[: args.body_cap], rec["title"])
            if t:
                terms[tok] = t
        if rec["status"] in ("deny", "fail", "empty"):
            errors.append({"token": tok, "title": rec["title"], "status": rec["status"]})

    # 重名分组
    by_title = defaultdict(list)
    for d in docs:
        by_title[d["title"]].append(d["token"])
    dup = {t: v for t, v in by_title.items() if len(v) > 1}
    for d in docs:
        d["dup_of"] = len(by_title[d["title"]]) if d["title"] in dup else 1

    total = len(docs)
    total_chars = sum(d["chars"] for d in docs)
    evident = [d for d in docs if d["evident"]]

    buckets = Counter()
    for d in docs:
        c = d["chars"]
        if c < 60:
            buckets["<60 空壳"] += 1
        elif c < 300:
            buckets["60-300 碎片"] += 1
        elif c < 1000:
            buckets["300-1k 短文"] += 1
        elif c < 5000:
            buckets["1k-5k 实质"] += 1
        else:
            buckets["≥5k 长文"] += 1

    inv = {
        "meta": {
            "total_docs": total,
            "total_chars": total_chars,
            "avg_chars": round(total_chars / total, 1) if total else 0,
            "evident_docs": len(evident),
            "evident_chars": sum(d["chars"] for d in evident),
            "evident_ratio": round(len(evident) / total * 100, 1) if total else 0,
            "meeting_docs": sum(1 for d in docs if d["is_meeting"]),
            "dup_title_groups": len(dup),
            "dup_extra": sum(len(v) - 1 for v in dup.values()),
            "errors": len(errors),
        },
        "stats": {
            "by_type": dict(Counter(d["type"] for d in docs).most_common()),
            "by_year": dict(sorted(Counter(d["year"] for d in docs).items())),
            "by_space": dict(Counter(d["space"] for d in docs).most_common()),
            "char_buckets": dict(buckets.most_common()),
            "top_dup": sorted(((k, len(v)) for k, v in dup.items()),
                              key=lambda x: -x[1])[:15],
        },
        "docs": docs,
        "terms": terms,
        "errors": errors[:500],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(inv, ensure_ascii=False), encoding="utf-8")

    m = inv["meta"]
    print(f"文档 {m['total_docs']} 篇 / {m['total_chars']:,} 字 / 均 {m['avg_chars']}")
    print(f"证据可用 {m['evident_docs']} 篇 ({m['evident_ratio']}%)，占字数 "
          f"{m['evident_chars']/max(m['total_chars'],1)*100:.1f}%")
    print(f"空壳 {buckets['<60 空壳']} / 碎片 {buckets['60-300 碎片']} / 重名组 {m['dup_title_groups']} / 失败 {m['errors']}")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
