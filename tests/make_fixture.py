#!/usr/bin/env python3
"""生成假飞书语料，用于验证 skill 全链路。不含任何真实内容。

用法:
  python3 tests/make_fixture.py --out tests/fixtures/raw --count 420
"""
import argparse
import json
import random
from pathlib import Path

SPACES = ["产品研发", "增长投放", "用户运营", "数据分析", "团队管理", "财务测算"]
TITLES = ["周报", "复盘", "方案", "需求分析", "数据排查", "月度目标", "项目计划", "会议纪要",
          "SOP", "测试方案", "竞品分析", "预算表", "排期", "上线检查", "问题清单"]
NOUNS = ["转化率", "填充率", "留存", "曝光", "点击", "成本", "收入", "预算", "排期", "库存",
         "客单价", "复购", "投放", "承接", "漏斗", "口径", "样本量", "对照组", "放量", "结算"]
VERBS = ["必须", "建议", "不要", "应该", "优先", "禁止", "需要"]
RULES = ["先小流量验证再放量", "同口径才能比较", "样本不足不下结论", "把风险条件写进方案",
         "指标定义变更要留记录", "每周固定复盘一次", "预算按批次释放", "异常先止损再定位"]


def make_doc(rng, idx, total):
    space = SPACES[idx % len(SPACES)]
    title = f"{rng.choice(TITLES)}-{idx:04d}" if idx % 37 else "周报"   # 制造重名
    if idx < 3:
        return {"token": f"tok{idx:04d}", "title": f"空文档-{idx}", "space": space,
                "type": "docx", "chars": 0, "text": "", "created": "2024-01-01", "links": []}

    paras = [f"## 背景\n本文讨论 {space} 相关的 {rng.choice(NOUNS)} 问题。"]
    for _ in range(rng.randint(2, 6)):
        n = rng.choice(NOUNS)
        v = rng.choice(VERBS)
        r = rng.choice(RULES)
        pct = round(rng.uniform(5, 80), 1)
        body = (f"## {n}分析\n本期{n}为 {pct}%，较上期{'上升' if rng.random()>0.5 else '下降'} "
                f"{round(rng.uniform(0.5,9),1)} 个百分点。\n"
                f"- {v}{r}，因为{rng.choice(NOUNS)}的口径不一致会导致误判。\n"
                f"- 该批投放成本 {rng.randint(3,90)} 万元，收入 {rng.randint(10,300)} 万元。\n")
        paras.append(body)
    text = "\n".join(paras)

    # 随机加内链（指向已存在的其他文档）
    links = []
    if idx > 5 and rng.random() < 0.35:
        for _ in range(rng.randint(1, 3)):
            j = rng.randint(3, idx - 1)
            links.append(f"tok{j:04d}")
            text += f"\n参见 [相关文档](https://demo.feishu.cn/docx/tok{j:04d})。\n"

    return {"token": f"tok{idx:04d}", "title": title, "space": space, "type": "docx",
            "chars": len(text), "text": text,
            "created": f"20{rng.choice([22,23,24,25,26])}-{rng.randint(1,12):02d}-{rng.randint(1,28):02d}",
            "links": links}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tests/fixtures/raw")
    ap.add_argument("--count", type=int, default=420)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    out = Path(args.out)
    (out / "docs").mkdir(parents=True, exist_ok=True)

    rows = []
    for i in range(args.count):
        d = make_doc(rng, i, args.count)
        (out / "docs" / f"{d['token']}.txt").write_text(d["text"], encoding="utf-8")
        rows.append({
            "token": d["token"], "node_token": "", "title": d["title"], "type": d["type"],
            "space": d["space"], "path": d["title"], "created": d["created"],
            "modified": d["created"], "source": "fixture", "has_child": False, "depth": 0,
            "url": f"https://demo.feishu.cn/docx/{d['token']}",
            "chars": d["chars"], "status": "ok" if d["text"] else "empty",
        })

    with (out / "manifest.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"生成 {len(rows)} 篇假语料 → {out}")
    print(f"  空间 {len(SPACES)} 个 / 空壳 3 篇 / 重名组 约 {len(rows)//37} 组")


if __name__ == "__main__":
    main()
