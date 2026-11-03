# Lumen · Local business portal and AI support desk

**English** | [简体中文](README.zh-CN.md) · v0.5.3

A complete personal demo that runs on your computer: a customer website, SQLite business database, tickets, an administrator console, and a support workflow covering queries, drafts, quality checks, approval, automatic replies, and human handoff.

**The local business website always works independently.** No model or API key is needed to sign in, simulate business requests, manage accounts, or process tickets. A real language model is optional and adds intent classification, controlled rephrasing, and review.

The workflow draws on observable patterns in `last30days.json`. Model and client names are preserved; accounts, orders, usage, and policies are synthetic. The original export is neither required to run the project nor automatically uploaded. “Learning” means case preparation, rules, knowledge retrieval, and evaluation; no model weights have been fine-tuned.

## Choose your path

| Goal | Mode | Requirements |
|---|---|---|
| Explore the website, accounts, database, and complete ticket workflow | **1. Independent local mode** | Python 3.11+, no model service |
| Use a language model for support classification, wording, and review | **2. Real reply model** | Python plus your Base URL, API key, and model ID |

Both modes use the same website and database. Switching modes preserves your data. The customer-facing **model directory always simulates business requests**; it is separate from the model generating support replies.

## Before you start

1. Extract the project and open a terminal in the folder containing `README.md`, `support_agent/`, and `scripts/`.
2. Check that `python3 --version` reports **Python 3.11 or newer**.
3. Run the commands below from this project root.

The website uses the Python standard library: no npm installation, database server, or pip packages are required. On Windows, open PowerShell in the project folder, check `py -3 --version`, and replace `python3` below with `py -3`.

## 1. Independent local mode

Run:

```bash
python3 scripts/start_demo.py --provider local
```

The launcher creates the database, six accounts, and six sample tickets, then opens a browser. The usual address is [http://127.0.0.1:8080](http://127.0.0.1:8080). If occupied, it tries up to nine subsequent ports; **use the address printed in the terminal**.

- No `.env`, API key, or internet connection is needed. Explicit `--provider local` keeps model calls disabled even if model credentials are configured.
- Keep the terminal open. Press **Ctrl+C** to stop.
- On macOS, double-clicking `start-demo.command` also starts the site. It defaults to local mode; use the terminal command below for a real model.
- Add `--no-browser` to start without opening a browser.

For an exact port and no automatic browser:

```bash
python3 -m support_agent.portal --provider local --host 127.0.0.1 --port 8080
```

This module entrypoint does not switch ports automatically. Use `--port 8081` if necessary.

### Sign in

All initial passwords are **`Demo123!`**. Select an identity on the login page.

| Identity | Email | Scenario |
|---|---|---|
| Alex, administrator | `admin@lumen.test` | Tickets, global AI switch, accounts, plans, balances; personal view |
| Gu Yan, support | `support1@lumen.test` | Human replies, send suggestions, retract AI messages; personal view |
| Xu Qing, support | `support2@lumen.test` | Same support permissions; no global AI or financial controls |
| Lin Xiao | `alice@lumen.test` | Small negative balance and failed Claude requests |
| Chen Yu | `ben@lumen.test` | Exhausted quota and refund requests |
| Zhou Ning | `cora@lumen.test` | Invoices, client configuration, simulated requests |

Customers see only their own data and public messages. Internal suggestions, evidence and handoff notes are available to staff. The UI and sample conversations use Simplified Chinese. Click the **bottom-left avatar** to switch an admin/support account between its personal space and workbench. Personal space contains that account's own business records and tickets.

### Complete your first ticket

1. Sign in as **Zhou Ning**, open the model directory and simulate a 503 failure. This only writes local business data.
2. Create a ticket using the request's help button. Stay on that page: a generation notice appears, followed by the answer automatically. **Automatic replies are on by default; no admin login or refresh is needed.** Issues requiring human handling, failed checks and approval-dependent operations go to staff.
3. In a different browser or independent private window, sign in as **Gu Yan or Xu Qing**, open the ticket and send a human reply. Both views update live.
4. Send another customer question. During the **15-minute human priority window**, AI does not send directly. After **1 minute without a staff reply**, it creates a private suggestion. A timely human reply cancels the pending job; further customer input restarts the wait and invalidates older suggestions.
5. Staff can use **发送这条建议** to send the suggestion, or **撤回 AI 回复** beside an earlier AI message. The customer immediately sees a retraction placeholder. Retraction retains the audit record and does not reverse financial operations.

Explicit human takeover continues until **恢复 AI** is clicked. Ordinary human replies protect the conversation for 15 minutes by default, then a subsequent customer message can get an automatic answer again. Existing suggestions and manually regenerated drafts always require staff confirmation.

Ordinary tabs in the same browser share a login session. Use different browsers or independent private sessions to test two accounts concurrently.

### Administrator controls

- The top-bar AI switch immediately disables unsent automatic replies. New questions wait for staff; delayed suggestions after human involvement still work. Re-enabling does not publish existing drafts.
- **客户与账号 → 管理账号 → 编辑账号与余额** updates account details, local balances and quotas. Balance changes enter the ledger.
- **新增套餐 / 修改套餐** sets plan name, quota, usage, reset/expiry dates and status. Activating a plan deactivates other active plans for that account and preserves history. Customer views and subsequent tool queries use the updated data.
- Support staff can read ticket context, reply, publish nonfinancial suggestions and retract AI messages. They cannot modify accounts, balances, plans, refund approvals, knowledge or global settings. Balance-correction drafts require admin approval.

### Live updates

SSE notifications invalidate page data, which is fetched again under the current account permissions. Messages, retractions, ticket lists, the AI switch, plans and balances update without manual refresh. Model generation runs in the background. Unsent text, edits to the same draft and scroll positions are preserved.

Disconnected clients show a reconnecting notice and try a five-second fallback sync. Reconnection fetches current state. Open editing dialogs defer redraw until closed to protect unsaved work. Keep the server running; reply generation time depends on the model service.

## 2. Connect a real reply model through terminal prompts

**You do not need to create or edit a `.env` file.** Open a terminal in the project root and run this one command:

```bash
python3 scripts/start_demo.py --provider openai
```

Windows PowerShell:

```powershell
py -3 scripts/start_demo.py --provider openai
```

If configuration is missing, the application asks for it interactively. **Enter one value at a time and press Enter.** When finished, it starts the website and opens your browser.

| Prompt | What to enter |
|---|---|
| **API address / Base URL** | Your provider's API prefix, such as `https://your-service.example/v1`; press Enter for OpenAI's official address |
| **API Key** | Paste your provider's key and press Enter. **No characters or asterisks appear; this is expected** |
| **Model ID** | The exact ID available to your provider account; this cannot be empty |
| **API type** | Enter `1` for `/chat/completions`, or `2` for `/responses`; Enter defaults to `2` |

Prompts appear in Chinese, matching the website:

```text
真实回复模型 · 临时连接设置
API 地址（Base URL，回车使用 https://api.openai.com/v1）：
API Key（输入隐藏，粘贴后按 Enter）：
模型 ID（按服务商提供的名称原样输入）：
接口类型：1 = Chat Completions（/chat/completions）；2 = Responses（/responses）。
选择接口 [1/2，回车默认 2]：
```

This is a prompt preview, not a block of commands to paste. Invalid formats or empty required fields ask you to try again. Press **Ctrl+C** to cancel without saving configuration. You do not need to run a separate connection check before the startup command.

### Choose the endpoint

Use the API prefix supplied by your provider, including `/v1` only when required. Do not append `/responses` or `/chat/completions`; the application adds the endpoint:

| Selection | Example final URL |
|---|---|
| `1`: Chat Completions | `https://your-service.example/v1/chat/completions` |
| `2`: Responses | `https://your-service.example/v1/responses` |

For OpenAI's Responses API, accept the default address, enter your key and an available model ID, then select `2`. For other compatible services, follow their API documentation. Model IDs are sent unchanged.

The service/model must support **strict JSON Schema structured output**. The Chat Completions adapter also uses `max_completion_tokens` and `store=false`. Plain-text-only endpoints and native Anthropic Messages or Gemini protocols are not supported directly. See the [official structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs).

### Temporary configuration only

- Interactive input stays in the current Python process's memory for this website run. It is **not written to `.env`, code, the database, a configuration cache, or shell startup files**. The application does not export it back to the parent shell.
- Stopping and restarting, opening a new terminal, or launching another project copy asks you again. Business accounts and tickets remain in their database; model credentials do not.
- If you explicitly provided `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and `OPENAI_MODEL` in your current environment, those values are reused and only missing fields are requested. Set `OPENAI_API_MODE` to choose the protocol. This is your supplied environment, not an application cache.
- Keys do not appear in browser pages or normal logs. Hidden input is not entered as a shell command or added to shell history. The project does not upload configuration to cloud storage. **Actual model requests still send authentication and the required request data to your chosen API endpoint.**
- Version 0.3.2 no longer reads `.env` or supports `--env-file`. Existing files are left untouched.

### Try the real model

Starting real-model mode now makes three short live requests: classification, composition and review. These can incur provider charges. The website opens only after all three succeed; credential entry alone is not reported as a working connection. TLS, network, authentication, protocol and schema failures stop this startup with an explicit error. Local mode remains offline and independent; seeded tickets are still generated offline.

Customer messages show the actual reply source and the model name reported by the service. The staff “模型调用” panel records the configured and reported model names, protocol, stage results, timings, history message count and whether human replies were included. Runtime failures remain visible as degraded status, and checked local fallbacks are clearly labeled. Balance writes use a controlled business template. Human priority, the global switch and action approvals still govern sending.

Composition and review receive the same current business evidence, customer question and conversation history. A content rejection triggers at most one model revision followed by another review; only a checked answer can be published. The staff panel distinguishes a successful API call from an accepted answer and shows sanitized review feedback. An ordinary reply uses three model calls; a content revision adds up to two more.

Version 0.5.3 tracks topic switches within a ticket, excludes paused topics from current queries and actions, and fetches fresh facts when returning to an earlier issue. Ambiguous references are clarified. Quota queries include balance-fallback settings and explicit timezone conversions; exiting a client cannot create a refund request, and resetting quota is not classified as a password reset.

Version 0.5.2 separates known conversation numbers from verified monetary claims, preventing false fallback when quoting an error code, time, or explicitly attributed retained-balance request. Refund follow-ups fetch current order state and preserve the unfinished topic across acknowledgements. Natural-language recovery confirmations can resolve the ticket; tentative recovery or outstanding verification keeps it open. See the [verification record](docs/verification.zh-CN.md) for regression cases and live-model results.

All three stages receive this ticket's recent public customer, AI and human messages (up to 24 previous messages and about 16,000 characters). Truncation is labeled. Retracted text, private drafts, internal notes and other users' tickets are excluded. Tentative recovery asks for confirmation; explicit recovery can resolve the ticket. Known information is available to the model instead of treating every follow-up as a new issue.

Some python.org macOS installations lack a default CA file. The app loads trusted roots from `certifi` when installed and continues certificate and hostname verification. If needed, run `python3 -m pip install -U certifi` in the interpreter environment, or install the optional dependency with `python3 -m pip install -e ".[models]"`. Explicit `SSL_CERT_FILE` / `SSL_CERT_DIR` settings are respected.

After updating, stop and restart the server and reload existing browser pages once. Existing drafts are not sent retroactively; subsequent messages update automatically.

### Optional connection check and other flags

To test the service without starting the website:

```bash
python3 scripts/start_demo.py --provider openai --check-model
```

It prompts for missing settings and sends three short requests using a synthetic example: classification, composition and review. These can incur provider charges. It sends no existing tickets and creates no database. The command then exits and **discards its interactive input**; a subsequent startup asks again. First-time users can simply use the single startup command at the beginning of this section.

Add `--no-browser` to the launcher to avoid opening a browser. The fixed-port module entrypoint supports the same prompts:

```bash
python3 -m support_agent.portal --provider openai --port 8080
```

Advanced users can pass `--base-url`, `--model`, and `--api-mode`. Precedence is **CLI > process environment > interactive input for missing fields**. There is no API-key CLI argument, keeping keys out of process arguments and command history. For automation, use `--no-input` and supply configuration through the process environment; missing fields fail promptly without reading keys from a pipe.

Relative database paths use the project root with the launcher, or the current directory with the module entrypoint. The model receives the current question, limited conversation context, and scoped business evidence, with no database write tool. Raw exports and candidate training text are not automatically sent.

## Persistence and a fresh demo

For upgrades from v0.3.x, stop the old server with Ctrl+C, run the new code and reload the browser once. Startup migrates the existing database, adds two support accounts and applies the new automatic / 15-minute / 1-minute defaults once. Later restarts preserve the saved AI switch. Accounts, tickets, ledger and plans are retained. Old drafts are not automatically sent. Use `--database /absolute/path/to/old-project/runtime/lumen_desk.db` when running a new extracted copy to retain the old data; you can back up the database before upgrading.

Both modes default to `runtime/lumen_desk.db`; restarting preserves data. To create fresh accounts and tickets without deleting anything, choose a **new, nonexistent database file**:

```bash
python3 scripts/start_demo.py --provider local --database runtime/fresh_demo.db
```

Payments, refunds, invoices, balances, and usage are local simulation state. Successful simulated requests consume a fixed demo quota amount; there is no real billing, automatic renewal, periodic quota reset, or invoice email.

## Troubleshooting

| Symptom | What to check |
|---|---|
| Python missing or too old | Install Python 3.11+; use `py -3` on Windows |
| Missing module or script | Run from the root containing `support_agent/` |
| Website unavailable | Keep the terminal running; use its printed URL; try `--port 8090` |
| Missing settings with no input prompt | Run directly in Terminal / PowerShell, without a pipe; automation must supply process environment variables |
| Key input appears blank | Hidden input shows no characters; paste and press Enter |
| Configuration changes ignored | Restart and enter new values; update any CLI/environment overrides. Old `.env` files are no longer read |
| HTTP 401 / 403 | Provider URL, key, and model permissions |
| HTTP 404 / 405 | API prefix, protocol, model ID, and duplicated endpoint suffixes |
| HTTP 400 / 422 or invalid structured output | The chosen endpoint/model must support strict JSON Schema and adapter parameters |
| HTTP 429 / network failure | Provider quota, rate limits, and network; use `--provider local` meanwhile |
| Customer sees no reply | Check generation/handoff status; admin can inspect the AI switch, quality warnings, cooldown and operation approvals |
| Live sync is reconnecting | Keep the server running; updates resume on reconnect. After upgrading code, restart and reload old pages once |
| Support cannot find plan/balance or AI controls | These are admin-only controls in the admin workbench |
| Old drafts did not change | Model settings affect new generations; create a ticket or regenerate |
| A directory model cannot generate replies | The directory is a business simulation; live model access depends on your provider account |

## Data, knowledge, and evaluation

The private export contained 4,357 messages, 735 AI draft/reply records, and 574 records reporting tool use. These are descriptive counts, not resolution metrics. See the [workflow mapping](docs/desk-guide.zh-CN.md).

Optional local import:

```bash
python3 scripts/import_support_export.py --input /path/to/last30days.json
```

Unreviewed candidates go to ignored `data/output/chat_export/` and never enter the knowledge base, model service, or release ZIP automatically. The importer excludes AI drafts, internal notes, and unlabelled senders as answer examples. It preserves model names and redacts recognizable secrets and identifiers; free-text names and indirect identifiers still need human review.

The export cannot reveal the original full system prompt or hidden configuration. Validate workflow behavior with synthetic cases, then evaluate answer quality on reviewed data before considering fine-tuning.

## Tests, packaging, and optional Docker

Core tests need no additional packages:

```bash
python3 -m unittest discover -s tests -p 'test_desk.py'
python3 -m unittest discover -s tests -p 'test_live_workflow.py'
python3 -m unittest discover -s tests -p 'test_portal*.py'
python3 -m unittest discover -s tests -p 'test_model_connection.py'
python3 scripts/evaluate_desk.py
python3 scripts/package_demo.py
```

The complete legacy suite also needs optional PDF dependencies:

```bash
python3 -m pip install '.[pdf]'
python3 -m unittest discover -s tests
python3 scripts/evaluate_agent.py
```

Release ZIPs under `dist/` contain source, docs, and synthetic fixtures, excluding private exports, candidates, databases, sessions, `.env`, and Git history. Model adapters are tested with simulated responses; use your own configuration for live connection checks and support evaluation. The [verification record](docs/verification.zh-CN.md) distinguishes tested behavior from limits. Passing 29 synthetic workflow cases is not a production resolution rate.

Docker users can run `docker compose up --build` from the project root and stop with `docker compose down`. This Compose configuration is fixed to local mode and does not pass model credentials into containers. Use the interactive Python launcher for real models. The exposed port uses `SUPPORT_HOST_PORT` (8080 by default). Do not run Python and Docker on the same host port. Docker configuration is updated but a Docker build was not exercised for this release.

## Code and further reading

| Location | Purpose |
|---|---|
| `support_agent/portal.py` | Website/API entrypoint and connection check |
| `support_agent/desk/config.py` | Hidden terminal input, environment, CLI, and in-memory settings |
| `support_agent/providers.py` | Responses and Chat Completions adapters |
| `support_agent/desk/` | Business storage, tools, workflow, admin features, frontend |
| `support_agent/desk/data/` | Synthetic knowledge, model catalog, policy, regression fixtures |
| [Implementation guide](docs/desk-guide.zh-CN.md) | JSON patterns, data model, permissions, extension points |
| [Verification and screenshots](docs/verification.zh-CN.md) | Automated checks and browser walkthrough |
| [Original RAG documentation](README.rag.md) | Preserved CLI, governance pipeline, and 48-case baseline; uses different entrypoints |

This is a localhost personal demo with known initial passwords. Do not expose it directly to the public internet. Real payments, invoice email, attachments/OCR, production deployment, and model fine-tuning are outside this version's scope.
