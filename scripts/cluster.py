#!/usr/bin/env python3
"""feishu-brain · L2 分集层

从体检结果自动提出候选集，供用户/AI 确认后落定。

策略（按优先级）：
  1. 空间优先   —— 飞书的知识空间/文件夹本身就是人的分类，先信它
  2. 小桶合并   —— 不足门槛的空间按关键词相似度并入最近的大桶
  3. 大桶拆分   —— 超过语料 40% 的空间按关键词再切
  4. 关键词兜底 —— 无空间归属的文档，按关键词得分分配
  5. 未分类保留 —— 得分不够的不硬塞

用法:
  python3 cluster.py --inventory index/inventory.json --out index/sets.json --propose
  python3 cluster.py --inventory index/inventory.json --out index/sets.json --apply
"""
import argparse
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

MIN_DOCS = 40          # 单集最小篇数
MIN_RATIO = 0.05       # 或占语料 5%
MAX_SETS = 8           # 上限
BIG_RATIO = 0.40       # 超过这个比例视为过大，需要拆分
FLAT_THRESHOLD = 300   # 低于此篇数走扁平模式


def cosine(a, b):
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    if not common:
        return 0.0
    num = sum(a[k] * b[k] for k in common)
    den = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return num / den if den else 0.0


def profile(doc_tokens, terms):
    p = Counter()
    for t in doc_tokens:
        for w in terms.get(t, []):
            p[w] += 1
    return p


def name_from_terms(terms, k=3):
    """给一个桶取名：取最高频且最能代表的词。"""
    if not terms:
        return "未命名"
    return "·".join(w for w, _ in terms.most_common(k))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", default="index/inventory.json")
    ap.add_argument("--out", default="index/sets.json")
    ap.add_argument("--propose", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--min-docs", type=int, default=MIN_DOCS)
    ap.add_argument("--max-sets", type=int, default=MAX_SETS)
    args = ap.parse_args()

    inv = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    docs = inv["docs"]
    terms = inv.get("terms", {})
    total = len(docs)
    if total == 0:
        raise SystemExit("语料为空")

    out_path = Path(args.out)

    # ---------- apply：校验并落定 ----------
    if args.apply:
        sets = json.loads(out_path.read_text(encoding="utf-8"))
        assigned, dup = {}, []
        for s in sets["sets"]:
            s.setdefault("docs", [])
            for t in s["docs"]:
                if t in assigned:
                    dup.append(t)
                assigned[t] = s["id"]
        known = {d["token"] for d in docs}
        missing = [t for t in known if t not in assigned]
        sets["unclassified"] = [t for t in sets.get("unclassified", []) if t not in assigned]
        for s in sets["sets"]:
            s["doc_count"] = len([t for t in s["docs"] if t in known])
            s["chars"] = sum(d["chars"] for d in docs if d["token"] in set(s["docs"]))
        sets["status"] = "applied"
        sets["applied_at"] = datetime.now().isoformat(timespec="seconds")
        out_path.write_text(json.dumps(sets, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已落定 {len(sets['sets'])} 集，覆盖 {len(assigned)}/{total} 篇，"
              f"未分类 {len(sets['unclassified'])} 篇")
        if missing:
            print(f"⚠️ {len(missing)} 篇未分配，已自动归入未分类")
            sets["unclassified"].extend(missing)
            out_path.write_text(json.dumps(sets, ensure_ascii=False, indent=1), encoding="utf-8")
        if dup:
            print(f"⚠️ {len(dup)} 篇被重复分配，已按首个为准")
        return

    # ---------- 扁平模式 ----------
    flat = total < FLAT_THRESHOLD
    space_buckets = defaultdict(list)
    for d in docs:
        if d["status"] in ("deny", "fail", "empty"):
            continue
        key = d["space"] or ""
        space_buckets[key].append(d["token"])

    if flat:
        # 不分集：按空间做"标签"，一篇可多标签
        buckets = {}
        for key, toks in space_buckets.items():
            if not key:
                continue
            buckets[key] = {
                "id": f"T{len(buckets)+1:02d}",
                "name": key,
                "desc": f"{len(toks)} 篇",
                "doc_count": len(toks),
                "chars": sum(d["chars"] for d in docs if d["token"] in set(toks)),
                "top_terms": [w for w, _ in profile(toks, terms).most_common(5)],
                "docs": toks,
            }
        result = {
            "mode": "flat",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "note": f"语料 {total} 篇，低于 {FLAT_THRESHOLD}，不启用分集，改用标签索引",
            "sets": list(buckets.values()),
            "unclassified": [d["token"] for d in docs if not d["space"]],
            "status": "proposed",
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"扁平模式：{len(buckets)} 个标签，{len(result['unclassified'])} 篇无标签 → {out_path}")
        return

    # ---------- 标准模式 ----------
    min_size = max(args.min_docs, int(total * MIN_RATIO))
    profiles = {k: profile(v, terms) for k, v in space_buckets.items()}

    # 大桶拆分
    final = []
    for key, toks in space_buckets.items():
        if len(toks) > total * BIG_RATIO and len(toks) > min_size * 3:
            # 用桶内最强的 6 个词做种子，二次分配
            seeds = [w for w, _ in profiles[key].most_common(6)]
            sub = defaultdict(list)
            for t in toks:
                dt = set(terms.get(t, []))
                hits = [s for s in seeds if s in dt]
                best = max(hits, key=len) if hits else (key + "·其他")
                sub[best].append(t)
            for name, st in sub.items():
                final.append({"name": name, "docs": st, "terms": profile(st, terms)})
        else:
            final.append({"name": key or "未分类", "docs": toks, "terms": profiles[key]})

    # 小桶合并到大桶
    bigs = [b for b in final if len(b["docs"]) >= min_size]
    smalls = [b for b in final if len(b["docs"]) < min_size]
    if not bigs and smalls:
        bigs = [max(smalls, key=lambda b: len(b["docs"]))]
        smalls = [b for b in smalls if b is not bigs[0]]

    for sm in sorted(smalls, key=lambda b: -len(b["docs"])):
        if not bigs:
            bigs.append(sm)
            continue
        target = max(bigs, key=lambda b: cosine(sm["terms"], b["terms"]))
        if cosine(sm["terms"], target["terms"]) < 0.05:
            target = max(bigs, key=lambda b: len(b["docs"]))
        target["docs"].extend(sm["docs"])
        target["terms"].update(sm["terms"])

    # 超上限：合并最相似的
    while len(bigs) > args.max_sets:
        worst = None
        for i in range(len(bigs)):
            for j in range(i + 1, len(bigs)):
                s = cosine(bigs[i]["terms"], bigs[j]["terms"])
                if worst is None or s > worst[0]:
                    worst = (s, i, j)
        if not worst:
            break
        _, i, j = worst
        bigs[i]["docs"].extend(bigs[j]["docs"])
        bigs[i]["terms"].update(bigs[j]["terms"])
        bigs.pop(j)

    # 无空间归属的按关键词分配
    unclassified = []
    for d in docs:
        if d.get("space") or d["status"] in ("deny", "fail", "empty"):
            continue
        dt = set(terms.get(d["token"], []))
        if not dt:
            unclassified.append(d["token"])
            continue
        scored = [(cosine(Counter({w: 1 for w in dt}), b["terms"]), b) for b in bigs]
        scored.sort(key=lambda x: -x[0])
        if scored and scored[0][0] > 0.03:
            scored[0][1]["docs"].append(d["token"])
        else:
            unclassified.append(d["token"])

    bigs.sort(key=lambda b: -len(b["docs"]))
    result_sets = []
    for i, b in enumerate(bigs, 1):
        tt = [w for w, _ in b["terms"].most_common(6)]
        result_sets.append({
            "id": f"S{i:02d}",
            "name": (b["name"].split("·")[0] if b["name"] and not b["name"].startswith("未") else name_from_terms(b["terms"])),
            "desc": "",                       # 留给 AI/用户补
            "doc_count": len(b["docs"]),
            "chars": sum(d["chars"] for d in docs if d["token"] in set(b["docs"])),
            "top_terms": tt,
            "docs": b["docs"],
        })

    result = {
        "mode": "standard",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "status": "proposed",
        "criteria": {
            "min_size": min_size,
            "max_sets": args.max_sets,
            "note": "集名和描述建议由 AI 结合 top_terms 与真实文档改写，不要直接用这几个词拼",
        },
        "sets": result_sets,
        "unclassified": unclassified,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"语料 {total} 篇 → 候选 {len(result_sets)} 集，未分类 {len(unclassified)} 篇")
    for s in result_sets:
        print(f"  {s['id']} {s['name']:<16} {s['doc_count']:>5} 篇  "
              f"{s['chars']:>9,} 字  {'/'.join(s['top_terms'][:4])}")
    print(f"→ {out_path}")
    print("下一步：改 name/desc，确认归属后跑 --apply")


if __name__ == "__main__":
    main()
