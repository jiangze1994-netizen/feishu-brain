# 飞书知识大脑 · feishu-brain

把你的飞书文档变成一个**可检索、能带走、AI 能直接读**的个人知识库。

> 不依赖 Obsidian、Notion、有道云，不装任何软件。产物只有一个文件夹 + 一个 HTML，双击就开。

## 它解决什么

| 痛点 | 症状 | 这个 skill 怎么解 |
|---|---|---|
| **找不到** | 只记得内容，不记得标题；飞书搜索搜不到正文 | 本地全量索引，全文检索 3 秒命中 |
| **说不清** | 存了几百篇，答不出"我到底掌握什么" | 自动聚成 3–8 个集，每集提炼可复用的结论 |
| **带不走** | 换号、离职、权限变更，知识归零 | 落地纯本地文件，脱离飞书也能查 |
| **AI 读不了** | 每次问都要重新翻飞书 | AI 通过 skill 直接检索本地语料，带出处回答 |

## 安装

```bash
cp -r feishu-brain ~/.workbuddy/skills/
```

前置：WorkBuddy 已连接飞书（`lark-cli` 可用）+ Python 3.8+。不需要其他依赖。

## 用法

在 WorkBuddy 里直接说：

> 帮我用飞书文档建个知识大脑

它会依次跑：拉取 → 体检 → 分集 → 建链 → 出脑。分集那步会让你确认、改名、合并。

建好之后，问任何关于你自己工作的事：

> 我去年定过哪些目标？完成得怎么样？

AI 会先检索本地语料，再带出处回答，并指出口径冲突。

## 产物

```
~/.feishu-brain/
├── raw/
│   ├── docs/<token>.txt      # 正文纯文本
│   ├── manifest.jsonl        # 元数据
│   └── errors.jsonl          # 失败清单
├── index/
│   ├── inventory.json        # 体检结果
│   ├── sets.json             # 集与归属
│   ├── links.json            # 双链 + 相似度
│   ├── knowledge.json        # 知识条目（L3）
│   ├── brain-summary.md      # 全局视图（AI 每次先读）
│   └── *.csv                 # 三张表，Excel 直接开
├── 飞书知识大脑.html          # 双击打开
└── state.json                # 同步状态
```

## 三个能力，分清楚

| 能力 | 谁用 | 怎么用 |
|---|---|---|
| `飞书知识大脑.html` | 人 | 双击，搜索、筛选、点链接跳回飞书 |
| `search.py` | AI | 命令行检索，输出 markdown 表 |
| `index_doc` 索引文档 | 人 + 同事 | 回写一篇飞书文档，点开就是完整目录 |

## 设计原则

1. **先精准地少读。** 上千篇里真正有信息量的往往只占两三成，先筛出证据池再精读。
2. **不编。** 每条结论必须能回链到原文；语料里没有就明说没有。
3. **区分实测与推断。** 作者手写的链接标「实测」，算法算的相似度标「推断」。
4. **不预置行业分类。** 集从使用者自己的语料里长出来。
5. **纯本地。** 全程不上传，产物是本地文件。

## 目录

```
feishu-brain/
├── SKILL.md                 # AI 操作手册（触发词、流程、回答规则）
├── scripts/
│   ├── fetch.py             # 拉取（发现层三路合并）
│   ├── sync.py              # 增量同步
│   ├── inventory.py         # L1 体检
│   ├── cluster.py           # L2 分集
│   ├── distill.py           # L3 提炼原料
│   ├── links.py             # 双链 + 相似度
│   ├── search.py            # 检索（给 AI）
│   ├── build_html.py        # 出脑
│   └── index_doc.py         # 回写飞书索引文档
├── assets/brain-template.html
├── references/
│   ├── data-contract.md
│   └── pitfalls.md
└── tests/
    ├── make_fixture.py      # 造假语料
    └── run_tests.sh         # 一键全链路
```

## 自测

不需要真实飞书账号，用假语料跑全链路：

```bash
python3 tests/make_fixture.py --out tests/fixtures/raw --count 420
bash tests/run_tests.sh
```

## 已知边界

- 只能读**你有权限**的文档，无权限的抓不到（`errors.jsonl` 会列出原因）
- 表格类（多维表格/电子表格）只记元数据和链接，不抓内容
- 不做 RAG 问答、不做向量库——AI 靠关键词检索 + 读片段回答
- 语料更新需要重跑同步（可配每日定时任务）

## License

MIT
