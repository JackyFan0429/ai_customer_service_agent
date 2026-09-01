# 系统架构

## 目标

客服 Agent 在不泄露内部资料、不把历史回答误当作现行政策的前提下，为客户提供可追溯回答，并将需要实时数据或人工权限的问题安全升级。

## 请求流程

```text
客户问题
  → 会话上下文（最多保留 8 个短回合）
  → BM25 + 字符 n-gram 混合检索
  → 时效、冲突、受众与最低相关度过滤
  → 路由决策
      ├─ answer: 生成回答并返回证据
      ├─ clarify: 请求补充客户端、步骤和报错
      └─ escalate: 交由人工或实时工具处理
```

## 模块职责

| 模块 | 职责 |
| --- | --- |
| `krill_agent/retrieval.py` | 加载语料并执行依赖零外部服务的混合检索 |
| `krill_agent/policy.py` | 执行 P1/P2、时效、冲突、受众和路由规则 |
| `krill_agent/prompts.py` | 构建防提示词注入的模型输入 |
| `krill_agent/providers.py` | 本地确定性回答与 OpenAI Responses API 适配 |
| `krill_agent/session.py` | 保存有上限的进程内会话历史 |
| `krill_agent/agent.py` | 编排检索、策略、生成和引用 |
| `krill_agent/cli.py` | 单次与交互式命令行入口 |

## 证据层级

| 层级 | 内容 | 可用于回答的范围 |
| --- | --- | --- |
| P0 | 实时账户、订单和服务状态工具 | 当前尚未接入 |
| P1 | 在复核期限内的官方知识 | 可支持当前事实 |
| P2 | 已筛选的历史案例 | 仅作排障线索 |
| P3 | 未解决或低置信材料 | 不进入主检索语料 |

模型只接收通过客户披露规则的证据。`agent_internal` 正文不会被发送给模型，`restricted_internal` 不进入检索语料。

## Provider 边界

默认 `local` provider 便于离线验收。`openai` provider 使用 Responses API，发送 `instructions` 和文本 `input`，关闭响应存储，并限制输出长度。API Key 只从运行环境读取。

## 后续接入点

- Telegram webhook 适配器。
- 持久化会话和客户授权状态。
- P0 账户、订单、余额与服务状态工具。
- 人工工单创建与状态回写。
- 离线评估、线上抽检和反馈闭环。
