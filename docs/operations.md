# 运行与发布

## 本地验收

从仓库根目录运行：

```bash
python3 -m krill_agent.cli --json "Codex Base URL 应该怎么配置？"
python3 -m krill_agent.cli --json "帮我查一下我的订单为什么还没到账"
python3 -m unittest tests.test_agent tests.test_providers -v
```

预期第一条返回 `answer` 和证据，第二条返回 `escalate` 且不生成账户结论。

## 配置原则

- 开发和测试默认使用 `local`。
- 生产模型通过 `OPENAI_MODEL` 显式选择，不在源码中固定。
- 生产密钥通过部署平台的 Secret 管理注入。
- `OPENAI_BASE_URL` 仅在明确使用兼容网关时设置。
- 每次更新官方知识后，依次重跑冲突检查、语料构建和验证脚本。

## 发布检查表

1. 完整测试通过。
2. 官方知识均在 `review_after` 日期内。
3. 密钥与敏感信息扫描无结果。
4. 典型问题、模糊问题、账户问题和实时状态问题均通过回归测试。
5. 生产渠道具备人工升级出口。
6. 日志不记录 API Key、密码、完整支付凭证和未脱敏客户数据。

## 结构化响应

`AgentResponse` 包含：

| 字段 | 含义 |
| --- | --- |
| `answer` | 面向客户的文本 |
| `route` | `answer`、`clarify` 或 `escalate` |
| `reason` | 路由原因，供编排层和审计使用 |
| `citations` | 实际支持回答的公开证据 |
| `session_id` | 渠道会话标识 |
| `provider` | 本次使用的生成提供器 |

渠道适配器应根据 `route` 创建人工工单或继续对话，不应解析自然语言来猜测路由。

## 已知限制

- 会话只保存在当前进程内，重启后丢失。
- 没有实时账户或服务状态工具。
- 本地 provider 主要用于验证策略和链路，语言质量不等同于模型模式。
- 混合检索尚未加入向量嵌入和重排模型。
