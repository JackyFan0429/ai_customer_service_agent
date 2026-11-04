# 使用说明

[首页](../README.zh-CN.md) · [English](operations.md)

命令从项目根目录执行。Windows 将 `python3` 换成 `py -3`。

## 启动网站

```bash
python3 scripts/start_demo.py --provider local
```

本地模式只需 Python 3.11+，首次启动创建合成业务数据，从 8080 开始选择可用端口并打开浏览器。6 个[演示账号](../README.zh-CN.md#演示账号)初始密码均为 `Demo123!`。

默认自动回复。客服可发送内部建议、人工回复、接管工单、恢复 AI 和撤回 AI 消息。撤回后客户看到占位提示，审计记录保留；撤回消息不会撤销业务操作。

人工回复后优先 15 分钟，客户再次发消息且 1 分钟无人回复才生成内部建议。主动接管持续到点击“恢复 AI”。已有建议和手动重新生成的建议均需客服确认发送。

管理员可控制全局自动发送、修改账户余额和套餐。重新打开开关不会批量发送旧草稿。客服没有这些管理权限，但客服和管理员均可批准符合规则的余额回正，核验订单后修改发票抬头或不改金额地重开。退款和发票金额变更仍由管理员审批。[完整规则](business-rules.zh-CN.md)。

## 模型接入

```bash
python3 scripts/start_demo.py --provider openai
```

按提示输入 API 前缀、隐藏 Key、模型 ID 和协议：`1` 为 Chat Completions，`2` 为 Responses。只询问缺失项；地址直接回车使用 `https://api.openai.com/v1`。程序添加实际接口路径。

配置优先级为 **命令行参数 → 当前进程环境变量 → 交互补齐**。支持 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`OPENAI_MODEL`、`OPENAI_API_MODE`（`chat_completions` 或 `responses`）。可选参数包括 `--base-url`、`--model`、`--api-mode`、`--no-input`，不提供 Key 命令行参数。

启动器不读取 `.env`，不保存交互凭据，也不写入父终端。停止进程后输入失效；用户主动设置的环境变量不属于程序缓存。

接口及模型需支持**严格 JSON Schema 输出**；Chat 适配器还发送 `max_completion_tokens` 和 `store: false`。Anthropic Messages、Gemini 原生协议不能直接替代。

启动先验证分诊、生成和质检。如只想检测连接：

```bash
python3 scripts/start_demo.py --provider openai --check-model
```

该命令发送 3 次短合成请求，可能计费；结束后丢弃交互输入，不发送已有工单或创建数据库。正常启动已包含这项检查，无需先单独执行。

管理员“模型调用”面板记录配置及实际返回的模型名、协议、阶段、耗时、上下文覆盖和脱敏错误。“接口成功”与“内容检查通过”分开显示，运行中回退可见。初始化示例工单始终使用本地回复。

## 实时更新

SSE 通知触发各端按权限重新取数，同步消息、撤回、工单列表、AI 状态、套餐、余额和发票。断线时有 5 秒后备同步，重连后获取最新状态。

未发送文本和滚动位置保留；编辑弹窗打开时暂缓重绘，保护未保存内容。普通标签页共享登录 Cookie，多角色验收请使用不同浏览器或独立隐私会话。

更新应用代码后，重启服务并刷新旧页面一次，后续业务变化自动同步。


时区换算需要 IANA 时区数据库。若当前 Python 缺少该数据（Windows 常见），执行 `python3 -m pip install tzdata`。顶部入口可更正显示 / 事件时区，消息明确指定的时区优先。[定位规则](business-rules.zh-CN.md#请求编号与时区)。

## 数据与启动选项

两种模式都使用 `runtime/lumen_desk.db`，重启保留账号和工单。新版本目录默认使用自己的数据库。要创建新演示而不删除旧数据：

```bash
python3 scripts/start_demo.py --provider local --database runtime/fresh_demo.db
```

如需继续使用原数据库，先备份，再通过 `--database` 指定绝对路径，启动时会迁移表结构。不要让两个不同版本同时使用同一数据库。

启动器加 `--no-browser` 可关闭自动打开浏览器。需要固定端口、不自动换端口时：

```bash
python3 -m support_agent.portal --provider local --host 127.0.0.1 --port 8080
```

启动器的相对数据库路径基于项目根目录；模块入口则基于当前目录。

项目也包含可选的本地 Docker 配置：

```bash
docker compose up --build
```

Compose 启动的是**当前网站的本地模式**，仅映射回环地址，并保留 `./runtime`。根目录 `.env.example` 只有可选宿主端口配置，不用于模型凭据。v0.5.10 未构建或验证 Docker。

用量、退款、发票和余额均为模拟状态；额度定时刷新、扣额度及扣余额写入本地数据库，不含真实支付、自动续费或邮件发送。v0.5.9 迁移只替换未自定义的旧默认知识，保留自定义内容及停用状态；自定义规则需另行核对。

## 常见故障

| 现象 | 检查项 |
|---|---|
| 找不到脚本或模块 | 在解压后的项目根目录使用 Python 3.11+ |
| 网站打不开 | 保持终端运行，使用终端显示的端口 |
| Key 输入没有任何显示 | 属于隐藏输入，粘贴后按回车 |
| 没有出现配置提示 | 参数或环境变量已提供；管道输入不是交互终端 |
| HTTP 401 / 403 | Key、接口地址、模型权限 |
| HTTP 404 / 405 | API 前缀、协议、是否重复填写接口后缀 |
| HTTP 400 / 422 或结构化输出错误 | 是否支持严格 JSON Schema 及适配器参数 |
| TLS 证书错误 | 配置当前 Python 的可信根证书；可选执行 `python3 -m pip install -e ".[models]"` 安装 certifi |
| 客户未收到自动回复 | 查看 AI 开关、人工优先、质检失败或操作审批 |
| 回复标为本地回退 | 在管理员面板查看失败阶段及脱敏原因 |
| 旧建议没有变化 | 新配置只用于后续生成，不改写旧建议 |
| 找不到套餐或余额编辑 | 任意余额及套餐编辑在管理员工作台；客服通过工单办理合规回正及发票操作 |

TLS 始终验证证书及主机名；显式设置的 `SSL_CERT_FILE` / `SSL_CERT_DIR` 优先。


管理员依据、`/recharge`、消息可见范围及费用单价设置见[专用说明](admin-evidence.zh-CN.md)。
