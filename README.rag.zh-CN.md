> Legacy RAG baseline documentation. For the current portal, see [README](README.md).

# 智能客服 Agent 与知识库治理

[English](README.rag.md) | **简体中文**

按照本教程，你可以在本机运行一个个人客服原型：检索知识、回答有依据的问题、追问缺失信息，并将账户类请求引导至人工核验。项目尚未接入真实客服业务。

默认 `local` 模式使用 **19 条虚构知识记录**，**不需要 API Key，也不会调用模型 API**。ClientA、ClientB Code、ClientC、ClientD 和 ModelA 都是虚构标签。示例知识和回答主要使用简体中文。

[获取文件](#get-the-files) · [Python 本机运行](#python-demo) · [Docker 运行](#docker-demo) · [复现示例对话](#demo-conversation) · [测试与评测](#verification) · [常见问题](#troubleshooting)

<a id="get-the-files"></a>
## 1. 获取项目文件

克隆仓库并进入目录：

```bash
git clone https://github.com/JackyFan0429/ai_customer_service_agent.git
cd ai_customer_service_agent
```

也可以下载仓库 ZIP，解压后在该目录打开终端。已经有本地项目的读者，直接进入已有目录即可。**以下命令都在同时包含 `README.md`、`support_agent/` 和 `compose.yaml` 的项目根目录执行。**

接下来选择 **Python 或 Docker 中的一条路径**。两者默认都使用 `8080` 端口，切换运行方式前请先停止另一种方式启动的服务。

<a id="python-demo"></a>
## 2A. 使用 Python 在本机运行

### A1. 创建 Python 环境

准备带有 `venv` 支持的 **Python 3.11 或更新版本**。CI 使用 Python 3.13。只有克隆仓库和后面的基线复现需要 Git。

**macOS / Linux：**

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python --version
```

**Windows PowerShell：**

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
```

如果 PowerShell 阻止激活脚本，将后续命令中的 `python` 换成 `.\.venv\Scripts\python.exe` 即可，无需修改执行策略。

Web 和 CLI 演示可以直接从源码目录运行，只使用 Python 标准库。**首次运行演示不需要执行 `pip install`。** 完整测试所需的额外依赖在后面单独安装。

### A2. 启动 Web 演示

```bash
python -m support_agent.web --provider local --host 127.0.0.1 --port 8080
```

保持此终端开启。正常启动时应看到：

```text
AI Customer Support is running at http://127.0.0.1:8080 (provider: local)
```

在浏览器打开 **[http://127.0.0.1:8080](http://127.0.0.1:8080)**，页面右上角应显示 `local · 虚构演示资料`。

也可以打开 **[健康检查地址](http://127.0.0.1:8080/api/health)**，直接确认后端状态：

```json
{"status": "ok", "provider": "local", "synthetic_demo": true}
```

如果之前配置过自定义语料，在启动命令后加上 `--corpus support_agent/demo/corpus.jsonl`，即可明确选择随包演示资料。

### A3. 体验对话，然后停止或重启

按[第 3 节](#demo-conversation)发送示例消息。在启动服务的终端按 **Ctrl+C** 停止服务，再运行同一条命令即可重启。未指定其他数据库时，会话保存在 `runtime/support_agent.db`；重启后刷新浏览器，点击原会话可确认历史仍在。

### A4. 可选：使用命令行对话

另开一个终端，进入项目根目录，并按照 A1 激活环境。先试一条返回结构化结果的问题：

```bash
python -m support_agent.cli --provider local --json "ClientA Base URL 怎么配置？"
```

预期结果包括 `route: "answer"`、带有虚构演示标记的配置说明，以及 `document_id: "demo:setup"` 的引用。

需要连续追问时，进入交互模式：

```bash
python -m support_agent.cli --provider local
```

逐条输入第 3 节的消息，最后输入 `exit` 退出。CLI 历史只保存在当前进程中；分别执行多条单次问答命令不会共享上下文。

<a id="docker-demo"></a>
## 2B. 使用 Docker 运行

这条路径不要求宿主机安装 Python。请安装带有 Compose 插件的 Docker，并**启动 Docker 引擎**。桌面版安装方式需要先打开应用并等待引擎就绪；如命令不可用，可参考[官方 Compose 安装说明](https://docs.docker.com/compose/install/)。

### B1. 检查 Docker

```bash
docker version
docker compose version
```

`docker version` 应同时显示 **Client** 和 **Server** 信息。只有客户端版本，不代表引擎已经启动。

### B2. 构建并启动

在项目根目录执行，确保 `8080` 端口没有被其他服务占用：

```bash
docker compose up --build -d
docker compose ps
```

首次构建需要联网获取 Python 基础镜像及打包工具。服务名为 `support-agent`，健康状态最终应变为 `healthy`；刚启动时可能短暂显示 `starting`。默认 provider 为 `local`，不需要 `.env` 文件或 API Key。

打开 **[http://127.0.0.1:8080](http://127.0.0.1:8080)**，按[第 3 节](#demo-conversation)操作。页面与健康检查地址的结果应和 Python 路径相同。Compose 默认仅将端口发布到本机回环地址。

### B3. 查看日志并在容器内试一次问答

```bash
docker compose logs --tail=50 support-agent
docker compose exec support-agent python -m support_agent.cli --provider local --json "ClientA Base URL 怎么配置？"
```

CLI 命令应返回 `route: "answer"`，引用为 `demo:setup`。

### B4. 验证会话保留，并停止服务

先在浏览器发送一条消息，再执行：

```bash
docker compose restart support-agent
```

刷新页面、选择原会话，应仍能看到历史消息。数据库位于宿主机项目目录的 `runtime/support_agent.db`，通过挂载映射到容器的 `/app/runtime`。

停止并移除本次演示容器：

```bash
docker compose down
```

这个命令会保留宿主机的 `runtime/` 目录和数据库。之后执行 `docker compose up -d` 即可再次启动；修改应用代码后，用 `docker compose up --build -d` 重新构建。

### B5. 可选：更换端口

如果 `8080` 已被占用，在 `compose.yaml` 同级创建 `.env` 文件，填写：

```dotenv
SUPPORT_HOST_PORT=8081
```

如果已有 `.env`，修改其中的端口设置即可，不要覆盖其他配置。然后执行：

```bash
docker compose up -d
```

改为访问 **[http://127.0.0.1:8081](http://127.0.0.1:8081)**。`SUPPORT_HOST_PORT` 只改变宿主机端口，容器内部仍使用 `8080`。Compose 会读取 `.env` 做[配置变量替换](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)。

<a id="demo-conversation"></a>
## 3. 按顺序复现示例对话

点击 **New conversation**，在**同一个会话里逐条发送**以下消息。原样复制问题可以复现本地规则模式的行为。

| 步骤 | 发送的消息 | 预期行为 |
| --- | --- | --- |
| 1 | `ClientA Base URL 怎么配置？` | `answer`：返回虚构配置说明，引用 `demo:setup`。 |
| 2 | `ClientB Code 401` | `answer`：提供鉴权检查建议，引用 `demo:401`。 |
| 3 | `现在变成 503 了` | `answer`：保留客户端上下文，改用 503 的处理依据，引用 `demo:503`。 |
| 4 | `还是不行` | `clarify`：结合当前主题询问已尝试步骤和新现象。 |
| 5 | `帮我退款` | `escalate`：提示人工核验，不声称已经退款。 |

浏览器显示回答正文和引用标题；`answer`、`clarify`、`escalate` 是 JSON 响应中的 `route` 值。`.example` 结尾的地址均为虚构地址，不能接入真实服务。此处的人工升级只表示路由和提示，不会创建真实客服工单。

<a id="verification"></a>
## 4. 运行测试并复现评测

以下是可选的开发者验证步骤，使用 **A1 创建的 Python 环境**。即使 Web 演示通过 Docker 启动，以下命令也在宿主机的项目根目录执行；轻量运行镜像不包含测试集和评测脚本。

### 4.1 安装测试依赖并运行软件测试

```bash
python -m pip install -e ".[pdf]"
python -m unittest discover -s tests -v
```

完整测试需要可选的 PDF 依赖。预期看到 **59 项测试**和 `OK`。涉及模型 API 的测试使用模拟响应，不会调用付费模型。

### 4.2 运行固定合成场景

```bash
python scripts/evaluate_agent.py --output runtime/evaluation.json --fail-on-regression evals/results/after.json
```

预期 **48/48 个场景**、**63/63 轮对话**和 **14/14 个多轮场景**通过，`failures: []`。打开 `runtime/evaluation.json` 可查看逐轮回答、检查结果和引用 ID。这条命令不需要 PDF 依赖，也不需要启动 Web 服务。

### 4.3 复现修复前的基线

先确保终端可以使用 Git，再执行：

```bash
python scripts/reproduce_baseline.py
```

脚本在临时目录还原修复前的逻辑并核对文件哈希，结果写入 `runtime/reproduced_before.json`。**39/48 是基线的预期结果**，其中包含 9 个已知失败场景；出现这些失败不表示基线复现失败。

| 指标 | 修复前 | 当前版本 |
| --- | --- | --- |
| 完整场景 | 39/48 | 48/48 |
| 完整轮次 | 53/63 | 63/63 |
| 路由正确 | 56/63 | 63/63 |
| 多轮场景 | 9/14 | 14/14 |
| 应升级召回 | 9/9 | 9/9 |

这些数字来自**合成开发回归集**，标签由 AI 编写、待项目本人复核，不代表独立盲测的模型准确率、线上解决率或满意度。评分使用明确词组与证据 ID；分母和限制见[评测说明](docs/evaluation.zh-CN.md)。

## 5. 可选：接入模型 API

建议先完成本地演示。这一步会将问题及筛选后的证据发送到配置的模型 API，可能产生费用。随包演示仅含合成资料，现有评测报告没有验证真实模型效果、Token 消耗或 API 成本。

**Python，macOS / Linux：**

```bash
export OPENAI_API_KEY="replace-with-your-key"
export OPENAI_MODEL="replace-with-your-model-id"
python -m support_agent.web --provider openai --host 127.0.0.1 --port 8080
```

**Python，Windows PowerShell：**

```powershell
$env:OPENAI_API_KEY = "replace-with-your-key"
$env:OPENAI_MODEL = "replace-with-your-model-id"
python -m support_agent.web --provider openai --host 127.0.0.1 --port 8080
```

将占位符替换为自己的密钥和模型 ID；如端口相同，先停止已运行的服务。当前 provider 使用 **Responses API**，自定义 `OPENAI_BASE_URL` 需要支持该接口，只有 Chat Completions 接口的服务不能直接替换。

**Docker：**参考 `.env.example`，在 `compose.yaml` 同级创建或编辑 `.env`：

```dotenv
SUPPORT_HOST_PORT=8080
SUPPORT_AGENT_PROVIDER=openai
OPENAI_API_KEY=replace-with-your-key
OPENAI_MODEL=replace-with-your-model-id
OPENAI_BASE_URL=https://api.openai.com/v1
```

然后重建容器实例：

```bash
docker compose up -d --force-recreate
```

页面状态栏应显示配置的 provider。恢复为 `SUPPORT_AGENT_PROVIDER=local` 后再次重建容器实例，即可回到离线演示。`.env` 被 Git 忽略且不会打入镜像。**直接运行 Python 时不会自动加载 `.env`**，请使用上面的终端环境变量命令。

## 6. 配置速查

| 变量 | 用途 | 默认值 |
| --- | --- | --- |
| `SUPPORT_AGENT_PROVIDER` | `local` 或 `openai`，命令行 `--provider` 优先 | `local` |
| `SUPPORT_AGENT_CORPUS` | 自定义检索 JSONL 路径 | 包内 `support_agent/demo/corpus.jsonl` |
| `SUPPORT_AGENT_DB` | SQLite 数据库路径 | `runtime/support_agent.db` |
| `SUPPORT_WEB_HOST` / `SUPPORT_WEB_PORT` | Python Web 监听地址和端口 | `127.0.0.1` / `8080` |
| `SUPPORT_HOST_PORT` | 仅用于 Compose 的宿主机端口 | `8080` |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | 模型密钥和模型 ID | 未设置 |
| `OPENAI_BASE_URL` | Responses API 地址 | `https://api.openai.com/v1` |

Compose 转发 provider 和 API 配置，容器内路径使用 Dockerfile 中的固定设置。接入私有资料时，可先按[本机知识导入流程](docs/operations.zh-CN.md)操作；仅设置宿主机语料路径，不会自动将文件挂载进容器。

<a id="troubleshooting"></a>
## 7. 常见问题

| 现象 | 处理方法 |
| --- | --- |
| `No module named support_agent` | 在解压后的项目根目录执行，使用 A1 的环境，确认存在 `support_agent/`。 |
| Python 低于 3.11 | 安装受支持的版本，用该解释器重新创建 `.venv`。 |
| `Address already in use` | 停止旧服务，或 Python 加 `--port 8081`、Compose 设置 `SUPPORT_HOST_PORT=8081`，浏览器也访问新端口。 |
| Docker 无法连接 daemon | 启动 Docker 引擎，确认 `docker version` 包含 Server 信息。 |
| 容器退出或不健康 | 执行 `docker compose logs --tail=50 support-agent`，检查端口和 `.env`、终端中的 provider 配置。 |
| 测试提示缺少 `pdfplumber` | 使用运行测试的同一个 Python 执行 `python -m pip install -e ".[pdf]"`。 |
| 提示缺少模型密钥或模型 ID | Python 演示使用 `--provider local`；Compose 使用 `SUPPORT_AGENT_PROVIDER=local`。本地模式不需要模型密钥。 |
| 找不到自定义语料 | 公开仓库不含私有数据集，选择 `support_agent/demo/corpus.jsonl` 使用随包资料。 |
| 评测提示报告不可比较 | 复现时保持题目、语料和评分器不变；有意修改后应重新建立基线，不能当作同一实验直接比较。 |
| 英文 README 下回答仍是中文 | 当前演示语料和提示词主要为中文，这是预期行为；翻译文档不会改变应用语言。 |

## 8. 项目能力与数据范围

工作流结合 BM25、字符 n-gram 检索，以及来源优先级、时效、冲突、受众和完整错误标识检查；支持有限的本地追问处理及 SQLite 会话持久化。它不查询真实账户、不执行退款、不创建真实工单，也没有使用 embedding 或自主业务工具循环。

公开仓库只附带合成演示资料。**1,659 条案例**、**1,086 条检索记录**是另行保管的既往私有快照规模，不是下载包内的数据量。介绍项目时请结合[数据范围](docs/data_scope.zh-CN.md)说明。

[架构](docs/architecture.zh-CN.md) · [知识维护流程](docs/operations.zh-CN.md) · [评测](docs/evaluation.zh-CN.md) · [回答策略](docs/safety.zh-CN.md) · [项目讲解](docs/interview.zh-CN.md)
