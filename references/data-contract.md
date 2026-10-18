# 数据结构约定

各脚本之间只通过这些文件传递数据。改脚本时保持字段名不变，否则下游会静默出错。

## `raw/manifest.jsonl` — 文档清单（每行一条）

```json
{
  "token": "H6bbd8IGjofX0DxADo7cVZrxnFb",
  "node_token": "LbsIwqQnVix37MkQoUkcch6jnJg",
  "title": "埋点方案",
  "type": "docx",
  "space": "数据工程",
  "path": "数据工程/埋点方案",
  "created": "2026-09-24",
  "modified": "2026-09-24",
  "source": "wiki",
  "url": "https://xxx.feishu.cn/wiki/LbsIwqQnVix37MkQoUkcch6jnJg",
  "chars": 3421,
  "status": "ok"
}
```

| 字段 | 说明 |
|---|---|
| `token` | **主键**，docx/sheet 等的 obj_token；文件路径 `raw/docs/<token>.txt` |
| `node_token` | wiki 节点 token，仅 wiki 来源有；用于把链接里的 node_token 映射回 token |
| `type` | `docx` / `doc` / `sheet` / `bitable` / `slides` / `mindnote` / `file` |
| `source` | `wiki` / `drive` / `search` / `fixture` |
| `status` | `ok` / `skip` / `deny` / `fail` / `empty` / `meta-only` |
| `chars` | 去空白后的正文字数 |

## `index/inventory.json` — 体检结果

```json
{
  "meta": {
    "total_docs": 1084, "total_chars": 2860000, "avg_chars": 2638.4,
    "evident_docs": 412, "evident_chars": 1900000, "evident_ratio": 38.0,
    "meeting_docs": 96, "dup_title_groups": 41, "dup_extra": 133, "errors": 9
  },
  "stats": { "by_type": {}, "by_year": {}, "by_space": {}, "char_buckets": {}, "top_dup": [] },
  "docs": [ { "token": "", "title": "", "type": "", "space": "", "year": "",
              "created": "", "modified": "", "chars": 0, "url": "", "status": "",
              "has_number": true, "num_hits": 7, "is_structured": true,
              "is_meeting": false, "evident": true, "dup_of": 1 } ],
  "terms": { "<token>": ["客单价", "填充率"] },
  "errors": [ { "token": "", "title": "", "status": "deny" } ]
}
```

**`evident`（证据可用）判定**：`chars ≥ 300 且 数字句 ≥ 3 且 有 markdown 结构`。
不含任何行业词，对所有领域通用。

**`terms`** 来自作者手写的章节标题 + 短列表项 + 文档标题，不是全文 n-gram。

## `index/sets.json` — 集与归属

```json
{
  "mode": "standard",
  "status": "proposed",
  "criteria": { "min_size": 43, "max_sets": 8 },
  "sets": [ { "id": "S01", "name": "增长投放", "desc": "",
              "doc_count": 312, "chars": 460000,
              "top_terms": ["填充率", "ecpm"],
              "docs": ["token1", "token2"] } ],
  "unclassified": ["token9"]
}
```

`mode`：`standard`（≥300 篇分集）/ `flat`（<300 篇改标签）
`status`：`proposed`（待确认）/ `applied`（已落定）

## `index/links.json` — 双链

```json
{
  "stats": { "docs_with_outlink": 147, "coverage": 35.0, "edges": 293, "avg_out": 1.99 },
  "outlinks": { "<token>": ["<token>", "..."] },
  "backlinks": { "<token>": ["<token>", "..."] },
  "similar": { "<token>": [["<token>", 0.82], ["<token>", 0.61]] }
}
```

- `outlinks` / `backlinks`：**L1 实测**，来自正文里作者手写的链接
- `similar`：**L3 推断**，关键词相似度，展示时必须标注

## `index/knowledge.json` — 知识条目

```json
{
  "items": [ {
    "id": "S01-K01",
    "set": "S01",
    "set_name": "增长投放",
    "title": "放量前先确认结算能力",
    "conclusion": "一句话结论，≤60 字",
    "detail": "展开说明，≤300 字",
    "evidence": "A",
    "sources": ["<真实存在的 token>"],
    "first_seen": "2024-03",
    "last_updated": "2026-09"
  } ]
}
```

`evidence`：`A` 原文明确 / `B` 多篇可推 / `C` 单一来源或 AI 纪要 / `缺` 无支撑

**硬规则**：`sources` 里的 token 必须真实存在于 `manifest.jsonl`，否则 HTML 里点不出原文。

## `state.json` — 同步状态

```json
{
  "owner": "张三",
  "updated_at": "2026-10-18T22:40:00",
  "docs": { "<token>": { "modified": "2026-09-24", "status": "ok", "chars": 3421, "title": "" } },
  "index_doc_token": "<飞书索引文档 token>",
  "index_doc_url": "https://...",
  "last_run": { "new": 12, "stats": {"ok": 12}, "gone": 0 }
}
```

`index_doc_token` 是幂等的关键：有它就走 `+update`，没有才 `+create`。

## `raw/docs/<token>.txt`

纯 markdown 正文，无 frontmatter、无额外元数据（元数据全在 manifest 里）。

**不要往里写双链、目录树、笔记软件格式**——这是纯文本语料，不是笔记。
