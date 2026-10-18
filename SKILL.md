---
name: feishu-brain
description: |
  把用户全部飞书文档（几百到上万篇）提炼成一个可检索、可带走的「数字大脑」。
  Build a searchable personal knowledge brain from a user's Feishu (Lark) documents.
  This skill should be used when the user asks to 建知识大脑、整理我的飞书文档、盘点我的飞书资料、
  我的飞书里都写了什么、我之前是不是写过、帮我找一份文档、把飞书文档同步下来、
  或者问任何关于其本人工作内容但需要翻飞书才能答的问题。
  也用于给已有大脑做增量同步（每天/每周）。
  适用于几百到上万篇文档；不依赖 Obsidian、Notion、有道云等任何第三方笔记软件。
agent_created: true
---

# 飞书数字大脑

把一个人的飞书文档变成**本地可检索语料库 + 索引 + 知识条目**，让 AI 能带出处地回答关于这个人的任何问题。

## 这个 skill 解决什么

用户飞书里有几百上千篇文档，但：
- **找不到**——只记得内容，不记得标题
- **说不清**——存了一堆，答不出自己到底掌握什么
- **带不走**——换号、离职、权限变动，知识归零

产物三层，缺一不可：

| 层 | 是什么 | 给谁用 |
|---|---|---|
| 语料层 | 全量纯文本 + 元数据 | 机器读 |
| 索引层 | 清单 / 集 / 双链 / 知识条目 | 机器读 |
| 视图层 | 单文件 HTML + CSV | 人看 |

## 三条路径，先判断走哪条

| 用户说的话 | 走这条 | 做什么 |
|---|---|---|
| "给我的飞书建个大脑" / "整理我的飞书" / "盘点我的文档" | **构建** | 从零跑完整流程 |
| "我之前是不是写过…" / "帮我找…" / "去年定的目标是啥" | **检索** | 直接查本地语料，建完才可用 |
| "更新一下" / "同步最新" | **同步** | 增量比对，只抓变化 |

判断依据：**看本地有没有已建好的大脑**（`~/.feishu-brain/index/brain-summary.md` 存在与否）。

## 第 0 步：前置检查（必须，别跳）

```bash
lark-cli --version                     # 1. 有没有 CLI
lark-cli docs +search -q "test" --format json | head -c 200   # 2. 有没有授权
python3 --version                      # 3. 有没有 Python 3.8+
```

任一不通，直接告诉用户缺什么、怎么补，**不要试图绕过去**。
授权失败时引导用户在 WorkBuddy 里重新连接飞书，不要自己造 token。

## 路径一：构建（从零）

用户在 WorkBuddy 里说"帮我建个飞书知识大脑"时，按顺序执行。**每段跑完先给用户看结果，再往下走。**

```bash
BRAIN=~/.feishu-brain
SKILL=~/.workbuddy/skills/feishu-brain/scripts

# 1 拉取（约 3–25 分钟，视语料量）
python3 $SKILL/fetch.py --out $BRAIN/raw --workers 6

# 2 体检（秒级）
python3 $SKILL/inventory.py --raw $BRAIN/raw --out $BRAIN/index/inventory.json
#    → 把「多少篇 / 多少字 / 多少重名 / 多少空壳」用一句话告诉用户

# 3 分集（需 AI 参与，见下）
python3 $SKILL/cluster.py --inventory $BRAIN/index/inventory.json \
        --out $BRAIN/index/sets.json --propose
#    → 拿到候选集，让用户确认/改名/合并，再跑 --apply

# 4 建链（秒级）
python3 $SKILL/links.py --raw $BRAIN/raw --sets $BRAIN/index/sets.json \
        --out $BRAIN/index/links.json

# 5 出脑（秒级）
python3 $SKILL/build_html.py --index $BRAIN/index --raw $BRAIN/raw \
        --out $BRAIN/飞书知识大脑.html

# 6 全局视图（AI 写，见下）
#    生成 $BRAIN/index/brain-summary.md，约 2000 字

# 7 回写飞书索引文档（可选，写操作前必须确认）
python3 $SKILL/index_doc.py --index $BRAIN/index --confirm
```

### 第 3 步的分集怎么做（唯一需要 AI 判断的地方）

`cluster.py --propose` 会吐出 3–8 个候选集，形如：

```json
[{"id":"S01","name":"候选名","doc_count":312,"top_terms":["ecpm","填充率","放量"]}]
```

拿到候选后：
1. **把集名改成用户能听懂的业务词**，不要用算法给的拼音式命名
2. 让用户确认：增、删、并、改名，都听用户的
3. 用户确认后 `--apply` 写回 `sets.json`

分集原则（不满足就不该单独成集）：
- 每集 ≥ 40 篇 **或** ≥ 5% 语料
- 内部术语口径稳定（top_terms 能概括）
- 与其他集共现重合 < 40%
- 允许「未分类」存在，**不要为了凑整强行分配**

### 第 6 步的全局视图写什么

`brain-summary.md` 是 AI 的"开机自检"，**约 2000 字**，结构固定：

```markdown
# <用户名>的数字大脑

## 我是谁
（一段话：岗位、负责什么、在哪个城市、时间跨度）

## 语料概况
N 篇 / N 万字 / N 年；证据可用 N 篇

## 集地图
| 集 | 覆盖什么 | 篇数 |
|---|---|---|

## 各集关键结论
（每集 3–5 条，带证据等级）

## 常见问题怎么查
（"问收入目标" → 查 S01 + S04）
```

**必须基于真实语料写，不许编。**

## 路径二：检索（建好之后，最常用）

用户问任何关于其本人工作的问题，**先检索，再回答**：

```bash
python3 $SKILL/search.py --query "关键词1 关键词2" --top 15
python3 $SKILL/search.py --query "周报" --set S01 --since 2025-01-01
```

输出是 markdown 表：`得分 | 标题 | 日期 | 集 | 命中片段 | 链接`。

### 回答规则（这是本 skill 最重要的部分）

1. **先检索再回答。** 不许凭训练数据或想象回答用户本人的事。
2. **每条结论必须带出处**——文档标题 + 日期 + 链接。没有出处的话不要说。
3. **区分三种可信度**，并明确标注：
   - 原文明确写的 → 直接引用
   - 多篇综合推出 → 说"综合 N 篇推断"
   - 语料里没有 → **直接说没有**，不许圆场
4. **主动指出冲突。** 同一指标不同文档口径不一致时，必须点出来（"8 月会议后口径改过，两篇数字对不上"）。
5. **默认只答有证据的部分。** 用户问三件事，只有两件有证据，就答两件，第三件明说查不到。

## 路径三：同步（增量）

```bash
python3 $SKILL/sync.py --brain ~/.feishu-brain            # 增量（默认 30 小时窗）
python3 $SKILL/sync.py --brain ~/.feishu-brain --full     # 全量补漏（慢，每周一次）
```

同步后自动重算索引，不需要手动跑其他脚本。

**双轨原则：**
- 每日增量用时间窗搜索，快（1–2 分钟），但会漏"别人新建、我首次获得权限"的
- 每周全量遍历一次，补上这个缺口
- 详见 `references/pitfalls.md`

## 反模式（别做这些）

- ❌ **只用 `drive +search --mine` 当发现层** → 系统性漏掉"有权限但非本人创建"的文档，实测漏 90%
- ❌ **把全文读进上下文** → 上千篇读不完，且抓不住重点
- ❌ **让 AI 自己编集名和结论** → 必须基于 `cluster.py` 的候选和真实命中片段
- ❌ **回答时分不清"原文写的"和"推断的"** → 用户会当真
- ❌ **宣布"全部读完了"但没统计覆盖率** → 必须报"成功 N / 失败 N / 无权限 N"
- ❌ **同步时写飞书** → 同步永远只读；唯一写操作是用户明确确认后的 `index_doc.py`
- ❌ **假设用户装了什么笔记软件** → 这是纯独立方案，产物只有本地文件

## 目录约定

```
~/.feishu-brain/
├── raw/
│   ├── docs/<token>.txt        # 正文纯文本
│   ├── manifest.jsonl          # 每篇一条元数据
│   └── errors.jsonl            # 失败清单（含原因）
├── index/
│   ├── inventory.json          # 体检结果
│   ├── sets.json               # 集与归属
│   ├── links.json              # 双链 + 相似度
│   ├── knowledge.json          # 知识条目（L3 产出）
│   └── brain-summary.md        # 全局视图（AI 每次先读这个）
├── 飞书知识大脑.html            # 双击打开
├── 语料清单.csv
├── 知识总表.csv
├── 集清单.csv
└── state.json                  # 同步状态
```

## 质量红线

- 证据等级 **A**（原文明确）/ **B**（多篇可推）/ **C**（单一来源或 AI 纪要）/ **缺**（无支撑）
- 双链里 **L1/L2 标"实测"，L3 相似度必须标"推断"**
- 索引文档里所有跳转链接必须是飞书原始 URL，不能是本地路径
- 报告覆盖率，不夸大

## 参考

- `references/data-contract.md` — 数据结构与字段定义
- `references/pitfalls.md` — 已知坑（必读，都是实盘踩过的）
