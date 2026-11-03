# 独立检索评测集

[文档索引](README.zh-CN.md) · [English](retrieval-dataset.md)

`lumen-retrieval-v1` 在 v0.5.5 建立，包含 **30 道合成题、10 条知识、22 个业务子问题组**，独立于 29 个网站业务场景，专门检查检索环节。

标签由 AI 辅助整理，全部为 `pending_owner_review`。“独立”指任务独立，不是第三方人工金标。v0.5.6 已完成[方法对照](retrieval-comparison.zh-CN.md)。

## 分区与分母

| 题目类型 | 开发集 | 保留集 | 评分 |
|---|---:|---:|---|
| 静态知识可答 | 15 | 7 | Recall、MRR |
| 知识＋业务数据 | 2 | 1 | 只评静态依据 |
| 知识无答案 | 2 | 1 | 误召回 |
| 纯动态查询 | 1 | 1 | 单列观察 |
| **合计** | **20** | **10** | 两个分区分别报告 |

Recall / MRR 分母为 **17** 和 **8**，不是 20 和 10。“当前余额多少”不能当作静态知识漏召回。

按业务子问题分组：开发集 14 组、保留集 8 组，成对改写留在同一侧。同一知识可跨分区支持不同子问题。校验器检查跨分区组和规范化后的完全重复，语义近似仍需人工复核。

## 标注方式

每题记录相关知识 ID、正文原文、标注理由、易混淆负例、必要业务工具和复核状态。正例必须直接支持当前问题，仅出现相同模型名或主题不算相关。组合题标出所有必要依据。

先阅读完整知识再标注，不按检索器排名挑答案。原文匹配只能检查引用出处，不能证明依据充分。

[开发集标注](../evals/retrieval/lumen-v1/development-review.zh-CN.md) · [保留集标注](../evals/retrieval/lumen-v1/holdout-review.zh-CN.md) · [知识快照](../evals/retrieval/lumen-v1/knowledge.json) · [分组及哈希清单](../evals/retrieval/lumen-v1/manifest.json)

## 校验命令

```bash
python3 scripts/validate_retrieval_dataset.py
```

预期为 `valid: true`、30 题、22 组、30 条待复核，输出至 `runtime/retrieval_dataset_validation.json`。

```bash
python3 scripts/validate_retrieval_dataset.py --require-reviewed --output runtime/retrieval-review-gate.json
```

标签未复核时，第二条命令应失败。必须实际复核后再填写审核人及批准状态；修改标签、知识或划分时另建数据版本和哈希，保留旧证据。

## 验证范围

每题使用完整语料，固定业务时间为 `2026-11-03T13:00:00+00:00`，复核期限为 `2027-02-01`。本集不验证知识过期、自动改写、连续对话状态或模型回答质量。

保留集文件公开提供。v0.5.6 结果公布后已不再是未见数据；若据此设计后续修复，应另建最终验证集。

