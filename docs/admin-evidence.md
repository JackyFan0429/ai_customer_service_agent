# Admin evidence and model usage

[Home](../README.md) · [Chinese](admin-evidence.zh-CN.md)

## Who sees what

| Content | Customer | Support | Admin workbench |
|---|---|---|---|
| Published final reply and model/source label | Yes | Yes | Yes |
| Final unpublished suggestion and send/retract controls | No | Yes | Yes |
| Knowledge IDs, retrieval scores, tool trace and evidence receipt | No | No | Yes |
| Correction success and current balance receipt | No | Yes | Yes |
| Model usage and cost-rate settings | No | No | Yes |

Switching an admin to personal view removes workbench access. The API filters private messages and run details before returning data. Ticket previews include public text only; SSE broadcasts a revision notification, then each client fetches its authorized data.

## Evidence receipt

Open a ticket as `admin@lumen.test`. A short internal message precedes the final reply: intent/route, selected IDs such as `ERR-401` + `PLAN-001`, BM25/character weights, actual business-query tools, checks and reply source.

In model mode, `evidence_summary` and `answer` are produced in the same structured composition response. The application adds the factual trace and rejects a summary citing unselected knowledge IDs. This is an evidence explanation, not private chain-of-thought. It adds output tokens but **no separate model call**. Local mode, financial templates and fallback use the application-generated trace; they are not presented as model-generated analysis.

Internal messages do not enter the model's subsequent public conversation context. If staff edit a final draft, the receipt still describes its original generation, not a new analysis of the edit.

The receipt distinguishes a real-model answer from a deliberate financial template and an actual fallback. Successful real-model triage followed by a transaction template is not a model failure. [Live examples](live-model-acceptance.md).

## Correction command

Support/admins can type exactly `/recharge` in the ticket reply box. It clears that customer's negative balance regardless of correction eligibility. It does not accept amounts, credit a positive balance or select a different account. A committed result appears only internally. Customers see their account balance update, not the command or success receipt.

Automatic correction requires an explicit request, eligible source/ledger, the $5 / seven-day rule and permission to send. Human takeover and disabled automatic sending hold a draft instead. Public replies do not claim success before the transaction commits.

## Usage and estimated cost

Open **Workflow settings** as an admin. The panel aggregates persisted ticket-run API calls, failures, retries, reported input/output tokens and model-stage elapsed time. Startup's three connection-check requests are **not included**. Latency here is accumulated API time, not customer waiting time.

Enter your provider's rates per million input/output tokens and a three-letter currency. Pricing first matches the reported model, then the requested model ID. With neither rate or missing usage, cost remains incomplete. Failed attempts with reported usage are counted. No provider price is guessed.

Estimates use current saved rates, so changing them recalculates the overview. They do not account separately for cached-token discounts, rate changes, taxes or minimum charges and are not an invoice. Prices are ordinary local settings; API keys still remain process-only. There is no measured claim of cost savings.
