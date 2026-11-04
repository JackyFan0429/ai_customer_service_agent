# Approved business rules

[Home](../README.md) · [Chinese](business-rules.zh-CN.md)

Implemented in **v0.5.9**, incorporating the ten-rule review and the later automatic-correction amendment. All accounts, money, invoices and platform status are local demo data.

## Permissions

| Operation | Customer | Support | Admin | AI |
|---|---|---|---|---|
| Read account, requests and invoices | Own account | Ticket's customer | Authorized customer | Ticket-scoped read tools |
| Change a Key's balance fallback | Own personal view | Own personal view only | Own personal view only | No |
| Clear an eligible negative balance | Request | Yes | Yes | Automatic after checks |
| Override correction eligibility with `/recharge` | No | Yes, current ticket | Yes, current ticket | No |
| Read technical evidence and model cost summaries | No | No | Yes, workbench only | Produce summaries |
| Edit invoice title or reissue without changing amount | No | Verify linked order first | Verify linked order first | Propose only |
| Approve refund or change invoice amount | No | No | Yes | No |
| Arbitrary balance changes, plans, account reset/activation | No | No | Yes | No |
| Send/edit a suggestion, reply, retract AI text, take over | No | Yes | Yes | Subject to workflow checks |
| Global AI automatic-send switch and platform status | No | No | Yes | No |

Switching between a staff workbench and personal space does not grant additional rights. AI read tools do not perform business writes.

## Quota and simulated usage

- An active, unexpired plan is used first. Quota resets at its configured UTC boundary; an expired plan is not renewed or refreshed.
- The interval defaults to **7 days**, configurable by admins from 1 to 366 days. Periods use fixed 24-hour days. Missed periods advance to the next future reset; unused quota does not accumulate.
- While running, maintenance checks due resets every second. Startup, account reads, workflow preparation and simulated requests also catch up. Refreshes are recorded in the quota ledger.
- A successful demo request costs **$0.12**. If quota covers the entire request, it deducts quota. Otherwise it requires the selected Key's enabled balance fallback and sufficient balance, then deducts the entire amount from balance. This demo does not split a request across quota and balance.
- Failed requests cost zero. Each new record contains its request ID, UTC time, billing source and ledger linkage. Old fixture records retain a legacy-source label.

Customers can enable fallback in **Account & usage**, then simulate a request in the model directory. Admins edit quota, reset time, expiry and interval on the customer account page. The plan editor labels UTC inputs explicitly.

## Balance corrections

An explicit correction request can be executed automatically after checks. Plain balance queries and policy questions do not authorize a write. Human priority, the global send switch and the automatic-correction setting can hold the action as a draft.

| Current debt | Successful correction history | Result, after source checks |
|---|---|---|
| Up to and including $5 | Any | Eligible; no seven-day limit |
| Above $5 | No correction above $5 in the last seven days | Eligible |
| Above $5 | A correction above $5 in the last seven days | Decline; ask for a top-up to cover the debt |

The rolling seven-day cutoff uses UTC and includes the boundary. Smaller corrections do not trigger the large-correction restriction. The current debt must match the latest qualifying request-overage ledger entry. Sending rechecks the amount and ledger ID; changed evidence invalidates the draft. Retraction never reverses a posted correction.

Support/admins may send exactly `/recharge` in the current ticket to bypass source, amount and recent-history eligibility. It clears only a negative balance; it cannot set arbitrary credit or reduce a positive balance. Customers and staff in personal view cannot invoke it. The success/current-balance receipt is committed with the ledger and visible only to support/admins; the customer account balance updates live. No success receipt is automatically posted publicly.

## Refunds and invoices

Refund requests stay on the same ticket; only admins approve their local status. AI does not invent refund amounts, completion or arrival dates.

For an invoice, staff must verify the linked order and explicitly confirm it in the ticket's invoice panel. Support can change the title or reissue with the same amount. Amount changes require admin access. Reissue cancels the old record and creates a new issued record; stale edits are rejected. Changes produce an audit event and a public staff message, synchronized to the customer.

Pending, issued, cancelled and emailed are different states. This demo has no invoice email delivery. A follow-up such as “Has the title changed?” queries the latest record instead of reopening the completed edit request.

## Request identity and time zones

1. Match by **ticket owner + request ID** first, even outside the recent 24-hour/30-record summary. Never substitute another account's record. Conflicting model, error or time descriptions are shown for clarification.
2. The request-help button saves a structured request ID and the server's authoritative timestamp, as well as the display zone. Text alone is not the association.
3. Event time-zone priority is **explicit in the message → customer selection → browser zone**. Each message retains its source. A staff browser's zone is not inferred as the customer's zone.
4. UTC is stored; Python converts event times using the event date's IANA rules or an explicitly given UTC offset. Generation and review receive the same UTC/local evidence.
5. Without an ID, a minute-level timestamp searches that minute, not only second zero. Missing year/zone, ambiguous or nonexistent daylight-saving times and multiple candidates require clarification. An existing unambiguous ID avoids unnecessary time questions.
6. Changing the display zone changes presentation, not the historical event. Staff can inspect UTC and the customer's event zone. Each request's own charge is reported, not a recent batch total.

Example: `2026-11-04 20:56 Australia/Sydney` is `09:56 UTC` and `17:56 Asia/Shanghai`. A separate event at `20:56 Asia/Shanghai` is `12:56 UTC`.

## Diagnosis and human collaboration

- 401/403 answers combine account, quota, Key metadata and configuration evidence. A saved setting or a client model label does not prove a successful connection. Credentials stay with the customer; model and client names remain visible.
- Current platform status includes both query time and record update time. It cannot establish the cause of an earlier request failure or an unrecorded recovery ETA.
- Account ownership and reset requests go to staff; reset and activation actions remain admin-only.
- Human replies give 15 minutes of priority by default. A subsequent customer message waits 60 seconds before an internal suggestion. A timely staff reply cancels generation; new customer input invalidates stale drafts. Explicit takeover lasts until staff resume AI, subject to the global switch.
- Public customer, AI and staff context is retained. Private drafts and retracted content are excluded. Customers see live public messages and a retracted placeholder, never internal suggestions.
- There is no image upload/OCR/vision pipeline. AI cannot claim to have seen an image; it reuses known information and asks only for missing diagnostic text. If the customer cannot supply it, the collected context goes to staff.

## Verification and remaining work

See [release verification](verification.md) for automated checks and local browser acceptance. This release changes business knowledge; frozen v0.5.6 retrieval scores do not measure these new entries. All 30 retrieval labels are owner-approved. Filtering and admin-only usage estimates are implemented; new unseen cases and a live-model pilot remain measurement work.
