# Operations

[Home](../README.md) · [Chinese](operations.zh-CN.md)

Run commands from the project root. Use `py -3` in place of `python3` on Windows. The UI and terminal prompts are in Simplified Chinese; control names below are translated.

## Start the website

```bash
python3 scripts/start_demo.py --provider local
```

Local mode needs Python 3.11+ only. It opens a browser, creates synthetic data on first launch and selects an available port starting at 8080. The initial password for all six [demo accounts](../README.md#demo-accounts) is `Demo123!`.

Automatic replies are on by default. Staff can send private suggestions, reply manually, take over a ticket, resume AI and retract AI messages. Retraction shows a placeholder to the customer and retains the audit record; it does not reverse business operations.

Human replies protect a conversation for 15 minutes. A subsequent customer message waits 1 minute for staff before generating a private suggestion. Explicit takeover continues until “Resume AI.” Existing or manually regenerated suggestions always require staff confirmation.

Admins can change the global automatic-send switch, account balances and plans. Turning the switch on does not publish existing drafts. Support staff cannot use these admin controls; balance-correction suggestions require admin approval.

## Model connection

```bash
python3 scripts/start_demo.py --provider openai
```

Enter the API prefix, hidden key, exact model ID and protocol. Choose `1` for Chat Completions or `2` for Responses. Missing values are requested; pressing Enter for the address uses `https://api.openai.com/v1`. The program appends the endpoint path.

Configuration precedence is **CLI options → process environment → prompts for missing values**. Supported environment names are `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL` and `OPENAI_API_MODE` (`chat_completions` or `responses`). Optional CLI flags include `--base-url`, `--model`, `--api-mode` and `--no-input`; there is no key CLI argument.

The launcher does not read `.env`, save interactive credentials or export them to the parent shell. Stopping the process discards interactive input. Environment variables explicitly set by the user are separate from that behavior.

The endpoint/model must support **strict JSON Schema output**. The Chat adapter also sends `max_completion_tokens` and `store: false`. Native Anthropic Messages and Gemini APIs are not direct substitutes.

Startup verifies triage, composition and review before opening the site. To perform only that check:

```bash
python3 scripts/start_demo.py --provider openai --check-model
```

This sends three short synthetic requests, may incur charges, then exits and forgets interactive settings. It sends no existing tickets and creates no database. Normal startup already includes the check.

The staff model-call panel records requested/reported model names, protocol, stage results, timings, history coverage and sanitized failures. A successful API response and an accepted answer are separate checks. Runtime fallback is visible. Seeded tickets use local responses even in model mode.

## Live updates

SSE notifications trigger an authorized refetch. Customer and staff views update messages, retractions, ticket lists, AI status, plans and balances. A five-second fallback sync helps during disconnection; reconnection fetches current state.

Unsent text and scroll position are preserved. Open editing dialogs defer redraw until closed to protect unsaved changes. Ordinary tabs share login cookies: test different roles in separate browsers or independent private sessions.

After changing application code, restart the server and reload existing pages once. Subsequent data changes synchronize automatically.

## Data and launch options

Both providers use `runtime/lumen_desk.db`. Restarting preserves accounts and tickets. A new release folder uses its own database unless an explicit path is supplied. To start fresh without deleting the old database:

```bash
python3 scripts/start_demo.py --provider local --database runtime/fresh_demo.db
```

For an existing database, back it up and pass its absolute path with `--database`. Startup applies schema migrations. Do not run two different releases against the same database simultaneously.

Add `--no-browser` to the launcher to keep the browser closed. For a fixed port without automatic port selection:

```bash
python3 -m support_agent.portal --provider local --host 127.0.0.1 --port 8080
```

Relative database paths are based on the project root in the launcher and on the current directory in the module entrypoint.

Optional local Docker configuration is included:

```bash
docker compose up --build
```

Compose starts the **current portal in local mode**, publishes it on loopback and persists `./runtime`. The root `.env.example` contains only an optional host-port setting; it is not a model credential file. Docker was not built or verified for v0.5.7.

Usage, refunds, invoices and balances are synthetic. There is no real billing, automatic renewal, scheduled quota reset or invoice email.

## Troubleshooting

| Symptom | Check |
|---|---|
| Script or module not found | Run inside the extracted project root with Python 3.11+ |
| Website unavailable | Keep the terminal running and use its printed port |
| Key input appears blank | Paste and press Enter; hidden input displays nothing |
| Settings are not requested | CLI/environment values already supplied them; pipes are not interactive terminals |
| HTTP 401 / 403 | Key, endpoint and model permissions |
| HTTP 404 / 405 | API prefix, selected protocol and duplicate endpoint suffix |
| HTTP 400 / 422 or schema error | Structured-output support and adapter parameters |
| TLS certificate error | Install trusted CA roots for this interpreter; optional `python3 -m pip install -e ".[models]"` supplies certifi |
| Customer receives no automatic answer | Inspect AI switch, human priority, review failure and action approval |
| Reply is labeled local fallback | Read the failed stage and sanitized reason in the staff panel |
| Old draft did not change | Generate a new reply; model settings do not rewrite earlier drafts |
| Plan/balance controls missing | Switch to the admin workbench; support has read-only business access |

TLS verification remains enabled, including when certifi is used. Explicit `SSL_CERT_FILE` / `SSL_CERT_DIR` settings take precedence.

