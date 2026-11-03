# 知识来源

[首页](../README.zh-CN.md) · [English](README.md)

| 范围 | 包内来源 |
|---|---|
| 当前网站 | `support_agent/desk/data/knowledge.json`：10 条合成规则，初始化载入 SQLite |
| 早期 RAG | `support_agent/demo/corpus.jsonl`：19 条合成记录 |
| 检索评测 | `evals/retrieval/lumen-v1/knowledge.json`：冻结的网站知识快照，用于复现 |

网站知识在管理员后台管理。[旧版导入流程](../docs/legacy/operations.zh-CN.md)生成独立 JSONL 语料，不会自动更新网站知识表。

本包不含真实公司文档。忽略规则覆盖 `knowledge/official/internal/`、`sources/` 和 `audit/`，**不是整个 `knowledge/official/` 目录**。私有材料应放在明确忽略的路径。发布脚本仅包含这两份知识说明，不包含私有来源目录。

保留来源、实际核验日期和有效期。[来源策略](../docs/legacy/official_kb_policy.md)。

