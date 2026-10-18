#!/usr/bin/env python3
"""feishu-brain · 出脑层

把索引 + 语料打成单文件 HTML，并导出三张 CSV。

不联网、不依赖任何框架，产物双击即可打开。

用法:
  python3 build_html.py --index index --raw raw --out 飞书知识大脑.html
  python3 build_html.py --index index --raw raw --out brain.html --owner 张三 --body-cap 3000
"""
import argparse
import csv
import json
from datetime import datetime
from pathlib import Path

TEMPLATE_DEFAULT = Path(__file__).resolve().parent.parent / "assets" / "brain-template.html"


def read_json(p, default=None):
    p = Path(p)
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_csv(path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="index")
    ap.add_argument("--raw", default="raw")
    ap.add_argument("--out", default="飞书知识大脑.html")
    ap.add_argument("--template", default=str(TEMPLATE_DEFAULT))
    ap.add_argument("--owner", default="")
    ap.add_argument("--body-cap", type=int, default=3000,
                    help="每篇嵌入 HTML 的正文字数上限")
    args = ap.parse_args()

    idx, raw = Path(args.index), Path(args.raw)
    inv = read_json(idx / "inventory.json")
    if not inv:
        raise SystemExit(f"找不到 {idx/'inventory.json'}，先跑 inventory.py")
    sets_doc = read_json(idx / "sets.json", {"sets": [], "unclassified": []})
    links = read_json(idx / "links.json", {})
    knowledge = read_json(idx / "knowledge.json", {"items": []})
    if isinstance(knowledge, list):
        knowledge = {"items": knowledge}

    docs_raw = inv["docs"]
    set_of, set_meta = {}, []
    for s in sets_doc.get("sets", []):
        kn = sum(1 for k in knowledge.get("items", []) if k.get("set") == s["id"])
        set_meta.append({
            "id": s["id"], "name": s.get("name") or s["id"],
            "desc": s.get("desc", ""), "doc_count": s.get("doc_count", len(s.get("docs", []))),
            "knowledge_count": kn,
        })
        for t in s.get("docs", []):
            set_of[t] = s

    skip_status = {"deny", "fail", "empty"}
    docs, bodies = [], {}
    for d in docs_raw:
        tok = d["token"]
        s = set_of.get(tok)
        docs.append({
            "token": tok,
            "title": d.get("title") or "(无标题)",
            "type": d.get("type", ""),
            "space": d.get("space", ""),
            "year": d.get("year", ""),
            "date": d.get("created") or d.get("modified") or "",
            "chars": d.get("chars", 0),
            "url": d.get("url", ""),
            "set": s["id"] if s else "",
            "set_name": s.get("name", "") if s else "",
            "evident": bool(d.get("evident")),
            "is_meeting": bool(d.get("is_meeting")),
            "status": d.get("status", ""),
        })
        p = raw / "docs" / f"{tok}.txt"
        if p.exists() and d.get("status") not in skip_status:
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
                bodies[tok] = txt[: args.body_cap]
            except Exception:
                pass

    total_chars = sum(d["chars"] for d in docs)
    meta = {
        "owner": args.owner,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "doc_count": len(docs),
        "char_count": total_chars,
        "evident_count": sum(1 for d in docs if d["evident"]),
        "stages_done": [x for x, ok in
                        (("L1", True), ("L2", bool(set_meta)),
                         ("双链", bool(links)), ("L3", bool(knowledge.get("items")))) if ok],
        "unclassified": len(sets_doc.get("unclassified", [])),
        "mode": sets_doc.get("mode", "standard"),
    }

    data = {
        "meta": meta,
        "sets": set_meta,
        "docs": docs,
        "bodies": bodies,
        "links": {k: links.get(k, {}) for k in ("outlinks", "backlinks", "similar")},
        "knowledge": knowledge.get("items", []),
    }

    tpl = Path(args.template).read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    if "/*__DATA__*/" not in tpl:
        raise SystemExit("模板缺少 /*__DATA__*/ 占位符")
    html = tpl.replace("/*__DATA__*/", payload)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    # ---- CSV ----
    write_csv(idx / "语料清单.csv",
              ["token", "标题", "类型", "空间", "年份", "字数", "是否会议", "含数字",
               "归属集", "处理状态", "原文链接"],
              [[d["token"], d["title"], d["type"], d["space"], d["year"], d["chars"],
                "是" if d["is_meeting"] else "", "是" if d["evident"] else "",
                (d["set"] + " " + d["set_name"]).strip(),
                d["status"], d["url"]] for d in docs])

    kn_rows = []
    for k in knowledge.get("items", []):
        srcs = k.get("sources", [])
        first = next((doc_map for doc_map in [d for d in docs if d["token"] in srcs]), None)
        kn_rows.append([
            k.get("id", ""), k.get("set", ""), k.get("set_name", ""),
            k.get("title", ""), k.get("conclusion", ""), k.get("evidence", ""),
            len(srcs), first["title"] if first else "", first["url"] if first else "",
            k.get("first_seen", ""), k.get("last_updated", ""),
        ])
    write_csv(idx / "知识总表.csv",
              ["知识ID", "集号", "集名", "知识标题", "一句话结论", "证据等级",
               "支撑文档数", "代表来源标题", "代表来源链接", "首次出现", "最近更新"],
              kn_rows)

    set_rows = []
    for s in set_meta:
        covered = [d for d in docs if d["set"] == s["id"]]
        ev = sum(1 for d in covered if d["evident"])
        set_rows.append([
            s["id"], s["name"], s["doc_count"],
            sum(d["chars"] for d in covered), s["knowledge_count"],
            f"{ev/len(covered)*100:.0f}%" if covered else "0%",
            "已提炼" if s["knowledge_count"] else "仅归属",
            s["desc"],
        ])
    write_csv(idx / "集清单.csv",
              ["集号", "集名", "覆盖文档数", "覆盖字数", "知识条数",
               "证据覆盖率", "状态", "备注"],
              set_rows)

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"HTML {size_mb:.1f} MB → {out}")
    print(f"  {len(docs)} 篇 / {total_chars:,} 字 / {len(set_meta)} 集 / "
          f"{len(bodies)} 篇内嵌正文（每篇 ≤{args.body_cap} 字）")
    print(f"CSV → {idx}/语料清单.csv · 知识总表.csv · 集清单.csv")
    if size_mb > 25:
        print("⚠️ 文件偏大，建议调小 --body-cap 或减少内嵌篇数")


if __name__ == "__main__":
    main()
