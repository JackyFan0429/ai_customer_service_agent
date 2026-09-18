# AI Customer Support Agent & Knowledge Base Governance

**English** | [简体中文](README.zh-CN.md)

Run a personal customer-support prototype on your own computer. The demo retrieves evidence, answers supported questions, asks for missing information, and routes account-specific requests to human review. It has not been connected to a real support operation.

The default `local` mode uses **19 fictional knowledge records**, needs **no API key**, and makes **no model API calls**. ClientA, ClientB Code, ClientC, ClientD, and ModelA are fictional labels. The sample knowledge and responses are mainly in Simplified Chinese; the walkthrough below provides exact prompts and explains their expected behavior in English.

[Get the files](#get-the-files) · [Python demo](#python-demo) · [Docker demo](#docker-demo) · [Demo conversation](#demo-conversation) · [Tests and evaluation](#verification) · [Troubleshooting](#troubleshooting)

<a id="get-the-files"></a>
## 1. Get the files

Clone the repository, then enter it:

```bash
git clone https://github.com/JackyFan0429/ai_customer_service_agent.git
cd ai_customer_service_agent
```

Alternatively, download the repository ZIP, extract it, and open a terminal in the extracted folder. If you already have the project locally, open that folder instead of cloning again. **Run every command below from the folder containing `README.md`, `support_agent/`, and `compose.yaml`.**

Choose **one** startup path. Python and Docker both use port `8080` by default, so stop one before starting the other.

<a id="python-demo"></a>
## 2A. Run with Python

### A1. Create a Python environment

Install Python **3.11 or newer** with `venv` support. Python 3.13 is used by CI. Git is only required for cloning and the optional baseline reconstruction.

**macOS / Linux:**

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python --version
```

**Windows PowerShell:**

```powershell
py -3 --version
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` in place of `python` in the following commands; changing your execution policy is unnecessary.

The web and CLI demos run directly from the source directory with the Python standard library. **No `pip install` is needed for this first demo.** Installing test dependencies is a separate step below.

### A2. Start the web demo

```bash
python -m support_agent.web --provider local --host 127.0.0.1 --port 8080
```

Keep this terminal open. A startup message should contain:

```text
AI Customer Support is running at http://127.0.0.1:8080 (provider: local)
```

Open **[http://127.0.0.1:8080](http://127.0.0.1:8080)** in your browser. The header should show `local · 虚构演示资料` (“local · synthetic demo data”).

Open **[the health endpoint](http://127.0.0.1:8080/api/health)** to check the server independently of the page:

```json
{"status": "ok", "provider": "local", "synthetic_demo": true}
```

If you previously configured a custom corpus, append `--corpus support_agent/demo/corpus.jsonl` to the startup command to select the packaged demo explicitly.

### A3. Try the conversation, then stop or restart

Follow [section 3](#demo-conversation). Press **Ctrl+C** in the server terminal to stop it. Run the same startup command again to restart; conversations persist in `runtime/support_agent.db` unless you configured a different database. Refresh the browser and select your previous conversation to confirm it is still present.

### A4. Optional: try the CLI

Open another terminal in the project folder and activate the environment as in A1. For a single question with structured output:

```bash
python -m support_agent.cli --provider local --json "ClientA Base URL 怎么配置？"
```

Expect `route: "answer"`, a fictional setup answer, and a citation with `document_id: "demo:setup"`.

For a multi-turn conversation:

```bash
python -m support_agent.cli --provider local
```

Enter the prompts from section 3 one at a time, then type `exit`. CLI history lasts only for that process; separate single-question CLI commands do not share conversation history.

<a id="docker-demo"></a>
## 2B. Run with Docker

This path does not require Python on your host. Install Docker with the Compose plugin and **start the Docker engine**. If you use a desktop installation, open it and wait until it is running. See the [official Compose setup guide](https://docs.docker.com/compose/install/) if the commands are unavailable.

### B1. Check Docker

```bash
docker version
docker compose version
```

`docker version` should show both **Client** and **Server** information. A client version alone does not mean the engine is running.

### B2. Build and start

From the project folder, with port `8080` free:

```bash
docker compose up --build -d
docker compose ps
```

The first build needs internet access to obtain the Python image and packaging tools. The service `support-agent` should become `healthy`; it may initially show `starting` while the health check runs. The default provider is `local`; no `.env` file or API key is needed.

Open **[http://127.0.0.1:8080](http://127.0.0.1:8080)** and follow [section 3](#demo-conversation). The page and health endpoint should show the same results as the Python path. Compose publishes the service only on your computer's loopback address.

### B3. Inspect the container

```bash
docker compose logs --tail=50 support-agent
docker compose exec support-agent python -m support_agent.cli --provider local --json "ClientA Base URL 怎么配置？"
```

The CLI command should return `route: "answer"` and cite `demo:setup`.

### B4. Verify persistence and stop

After sending a message in the browser:

```bash
docker compose restart support-agent
```

Refresh the page and select the conversation. Messages are stored in your project's `runtime/support_agent.db`, mounted into the container at `/app/runtime`. To stop and remove the demo container:

```bash
docker compose down
```

This keeps the host `runtime/` folder and its conversation database. To start again, run `docker compose up -d`. After changing application code, rebuild with `docker compose up --build -d`.

### B5. Optional: use a different port

If port `8080` is occupied, create a `.env` file next to `compose.yaml` containing:

```dotenv
SUPPORT_HOST_PORT=8081
```

If `.env` already exists, edit its port setting instead of overwriting the file. Apply the change:

```bash
docker compose up -d
```

Open **[http://127.0.0.1:8081](http://127.0.0.1:8081)**. `SUPPORT_HOST_PORT` changes the host port; the container still listens on `8080`. Compose reads `.env` for [configuration interpolation](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).

<a id="demo-conversation"></a>
## 3. Reproduce the demo conversation

Click **New conversation**, then send these messages **one at a time in the same conversation**. Copy the Chinese prompts exactly to reproduce the local rule-based behavior.

| Step | Message to send | Meaning | Expected behavior |
| --- | --- | --- | --- |
| 1 | `ClientA Base URL 怎么配置？` | How do I configure the base URL? | `answer`: fictional setup instructions; evidence `demo:setup`. |
| 2 | `ClientB Code 401` | ClientB Code returns 401. | `answer`: authentication checks; evidence `demo:401`. |
| 3 | `现在变成 503 了` | Now it has changed to 503. | `answer`: switches to the 503 guidance, retaining the client context; evidence `demo:503`. |
| 4 | `还是不行` | It still does not work. | `clarify`: asks what you tried and what happened, retaining the current topic. |
| 5 | `帮我退款` | Please refund me. | `escalate`: asks for human verification; does not claim a refund was issued. |

The browser shows answer text and evidence titles. `answer`, `clarify`, and `escalate` are the structured `route` values visible in JSON responses. Addresses ending in `.example` are fictional; do not use them as real service endpoints. Escalation here is a response and routing decision, not a real support ticket.

<a id="verification"></a>
## 4. Run tests and reproduce the evaluation

These optional developer checks use the **Python environment from A1**, including if you chose Docker for the web demo. The lightweight runtime image does not include the test suite or evaluation scripts.

### 4.1 Install test dependencies and run the tests

```bash
python -m pip install -e ".[pdf]"
python -m unittest discover -s tests -v
```

The optional PDF dependency is needed by the full suite. Expect **59 tests** and `OK`. API-related tests use mocked responses and do not call a paid model.

### 4.2 Run the fixed synthetic scenarios

```bash
python scripts/evaluate_agent.py --output runtime/evaluation.json --fail-on-regression evals/results/after.json
```

Expect **48/48 scenarios**, **63/63 turns**, **14/14 multi-turn scenarios**, and `failures: []`. Open `runtime/evaluation.json` for per-turn answers, checks, and evidence IDs. This command does not need the PDF dependency or a running web server.

### 4.3 Reconstruct the pre-fix baseline

With Git available in your terminal:

```bash
python scripts/reproduce_baseline.py
```

The script reconstructs the earlier logic in a temporary directory, checks its file hashes, and writes `runtime/reproduced_before.json`. **39/48 scenarios is the expected baseline**, including nine known failing scenarios; it is not a failure to reproduce the baseline.

| Metric | Before fixes | Current version |
| --- | --- | --- |
| Complete scenarios | 39/48 | 48/48 |
| Complete turns | 53/63 | 63/63 |
| Correct routes | 56/63 | 63/63 |
| Multi-turn scenarios | 9/14 | 14/14 |
| Required escalations recalled | 9/9 | 9/9 |

These are **synthetic development regression results**, with AI-authored labels awaiting owner review. They are not held-out model accuracy, production resolution rate, or customer satisfaction. The evaluator checks explicit phrases and evidence IDs. See [evaluation details](docs/evaluation.md) for denominators and limitations.

## 5. Optional: connect a model API

Complete the local demo first. This step sends questions and selected evidence to the configured model API and can incur charges. The packaged demo only contains synthetic data. Real model quality, token usage, and API cost have not been evaluated in the stored reports.

**Python, macOS / Linux:**

```bash
export OPENAI_API_KEY="replace-with-your-key"
export OPENAI_MODEL="replace-with-your-model-id"
python -m support_agent.web --provider openai --host 127.0.0.1 --port 8080
```

**Python, Windows PowerShell:**

```powershell
$env:OPENAI_API_KEY = "replace-with-your-key"
$env:OPENAI_MODEL = "replace-with-your-model-id"
python -m support_agent.web --provider openai --host 127.0.0.1 --port 8080
```

Stop the existing server first if it uses the same port. The provider uses the **Responses API**, so a custom `OPENAI_BASE_URL` must support that API; chat-completions-only endpoints are not interchangeable.

**Docker:** create or edit `.env` next to `compose.yaml` using `.env.example` as the template:

```dotenv
SUPPORT_HOST_PORT=8080
SUPPORT_AGENT_PROVIDER=openai
OPENAI_API_KEY=replace-with-your-key
OPENAI_MODEL=replace-with-your-model-id
OPENAI_BASE_URL=https://api.openai.com/v1
```

Then recreate the container:

```bash
docker compose up -d --force-recreate
```

The header should now display the configured provider. Restore `SUPPORT_AGENT_PROVIDER=local` and recreate it again to return to the offline demo. `.env` is ignored by Git and excluded from the image. **Native Python does not automatically load `.env`**; use the shell commands above for that path.

## 6. Configuration reference

| Variable | Purpose | Default |
| --- | --- | --- |
| `SUPPORT_AGENT_PROVIDER` | `local` or `openai`; explicit `--provider` wins | `local` |
| `SUPPORT_AGENT_CORPUS` | Custom retrieval JSONL path | Packaged `support_agent/demo/corpus.jsonl` |
| `SUPPORT_AGENT_DB` | SQLite database path | `runtime/support_agent.db` |
| `SUPPORT_WEB_HOST` / `SUPPORT_WEB_PORT` | Python web server binding | `127.0.0.1` / `8080` |
| `SUPPORT_HOST_PORT` | Compose host port only | `8080` |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | Model credentials and model ID | Unset |
| `OPENAI_BASE_URL` | Responses API base URL | `https://api.openai.com/v1` |

Compose forwards the provider and API settings and uses fixed container paths from the Dockerfile. To use private data, start with the [native custom-knowledge workflow](docs/operations.md); setting a host corpus path alone does not mount it into a container.

<a id="troubleshooting"></a>
## 7. Troubleshooting

| Symptom | What to do |
| --- | --- |
| `No module named support_agent` | Run the command from the extracted repository root, using the environment from A1. Check that `support_agent/` exists. |
| Python version is below 3.11 | Install a supported Python and recreate `.venv` with that interpreter. |
| `Address already in use` | Stop the previous server, or use `--port 8081` for Python / `SUPPORT_HOST_PORT=8081` for Compose; open the matching browser URL. |
| Docker cannot connect to its daemon | Start the Docker engine, then confirm `docker version` shows a Server section. |
| Container exits or is unhealthy | Run `docker compose logs --tail=50 support-agent`. Check port availability and any provider settings in `.env` or your shell. |
| Test run reports missing `pdfplumber` | Run `python -m pip install -e ".[pdf]"` with the same Python used for the tests. |
| Missing model key or model ID | Use `--provider local` for the Python demo; set `SUPPORT_AGENT_PROVIDER=local` for Compose. A model key is not required for local mode. |
| Custom corpus file is missing | The public repository does not include private datasets. Select `support_agent/demo/corpus.jsonl` for the packaged demo. |
| Evaluation says reports are incomparable | Keep the checked-in scenarios, corpus, and grading script unchanged for reproduction. If intentionally changed, create a new baseline instead of treating it as the same experiment. |
| Replies are in Chinese | This is expected for the provided fixtures and current prompts; changing the README language does not translate the application knowledge. |

## 8. What the project demonstrates

The workflow combines BM25 and character n-gram retrieval with source precedence, expiry, conflict, audience, and exact-error-identifier checks. It supports narrow local follow-ups and SQLite-backed web conversations. It does not query real accounts, issue refunds, create real tickets, use embeddings, or run an autonomous business-tool loop.

Only synthetic demo data ships in this repository. The historical figures of **1,659 cases** and **1,086 retrieval records** refer to a separate private snapshot, not the downloadable demo. See [data scope](docs/data_scope.md) before using those numbers in a project description.

[Architecture](docs/architecture.md) · [Knowledge workflow](docs/operations.md) · [Evaluation](docs/evaluation.md) · [Response policy](docs/safety.md) · [Project walkthrough](docs/interview.md)
