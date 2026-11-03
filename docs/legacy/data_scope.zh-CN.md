# 早期 RAG 数据范围

[旧版入口](README.zh-CN.md) · [English](data_scope.md)

这是个人项目，不是公司官方产品。旧语料使用虚构客户端、模型代号和 `.example` 地址；当前网站保留技术模型及客户端名称，业务记录仍为合成数据。

| 包内路径 | 内容 |
|---|---|
| `support_agent/demo/corpus.jsonl` | 19 条合成记录，模拟来源优先级 |
| `evals/scenarios.jsonl` | 48 个开发场景、63 轮消息 |
| `evals/results/` | 实际执行的历史前后报告及哈希 |
| `evals/baselines/pre_iteration.patch` | 历史代码补丁，需匹配源码快照 |

不包含原始客服案例、内部文档、私有衍生数据和运行数据库。早期私有处理规模不是公开语料规模，也不是仅凭本包可复现的结果。

准备私有输入时，将消息标识映射为 `message_id`，脱敏个人信息、复核来源与时效，再单独评测新语料。流程见[知识整理](operations.zh-CN.md)。来源文档和私有导出不会自动上传。

