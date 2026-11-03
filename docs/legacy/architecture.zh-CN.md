# 早期 RAG 架构

[旧版入口](README.zh-CN.md) · [English](architecture.md)

本页仅适用于 `support_agent.web` 和 `support_agent.cli`，业务网站见[当前架构](../architecture.zh-CN.md)。

```text
消息＋最近 8 条对话
  → 本地规则 / 模型结构化理解
  → 保留完整标识的独立查询
  → BM25＋字符 n-gram 检索
  → 相关性、时效、冲突及披露检查
  → 有预算的证据文本
  → 回答 / 澄清 / 升级人工
```

| 模块 | 职责 |
|---|---|
| `session.py` | 有限历史与未完成主题 |
| `providers.py` | 本地规则或模型理解、生成 |
| `retrieval.py` | 共用词面排序与完整标识 |
| `policy.py` | 来源时效、披露和升级策略 |
| `prompts.py` | 证据字符预算及不可信内容边界 |
| `agent.py` | 编排与引用元数据 |
| `database.py`、`web.py` | 独立对话存储和网页 |

P1 为已复核来源知识，P2 为历史排障线索，P3 为未解决资料；公开数据只模拟这些角色。此入口没有业务查询工具，升级只返回路由和提示，不会操作工单。

内部及受限正文不进入客户证据。引用只能说明提供了哪些材料，不证明每句答复成立。预算按字符计算，不是 Token。[当前检索对照](../retrieval-comparison.zh-CN.md)评估网站过滤流程，不等于此旧版完整回答链路。

