# 已复核检索评测集

[首页](../README.zh-CN.md) · [English](retrieval-dataset.md)

当前 [v3 快照](../evals/retrieval/lumen-v3)包含 **30 道人工确认题、22 个问题组、10 条业务知识**，与 29 个业务流程场景分别统计。题目为合成数据，不包含原始客户对话或密钥。

每题记录必要知识 ID、精确依据、解释、易混淆负例、必须 / 可选业务工具及用户确认。30 道审批均留在[复核日志](../evals/retrieval/lumen-v3/approval-log.json)。政策咨询不能执行操作；退款诉求需要查业务状态；当前余额与单次耗时不能靠静态知识回答。

开发集 20 题、14 组；历史保留集 10 题、8 组。同义改写留在同侧，不同业务子问题可复用知识 ID。分区已公开并复核，后续结果只能称诊断，不能再视为未见验证。

最新余额修订允许 AI 按条件自动回正，以及客服 / 管理员的 `/recharge`；成功回执仅内部显示。新标签和引用对应此规则。原 v1 语料和 v0.5.6 实验保持不变，供追溯。

```bash
python3 scripts/validate_retrieval_dataset.py --dataset evals/retrieval/lumen-v3 --require-reviewed --output runtime/reviewed-labels.json
```

预期为结构有效、30 题已通过、0 题待复核。校验只检查格式、引用、依据及分组，不运行检索，也不证明答案质量。[当前测量](evaluation.zh-CN.md)。
