# v0.5.9 review implementation

[Chinese](reviewed-changes.zh-CN.md) · [Business rules](business-rules.md)

Built independently from v0.5.8. Earlier projects and running databases are untouched.

| Decision | Implementation | Verification |
|---|---|---|
| Approve RET-029/030 | All 30 labels approved in v3 | Strict dataset gate |
| Distinguish rule consultation, business facts and missing knowledge | Subject/capability filter; no unsupported model specifications or error aliases | Reviewed retrieval and workflow tests |
| AI may correct eligible debt | Explicit request, source/ledger checks, $5/seven-day policy and transactional recheck | Eligibility, idempotence and rollback tests |
| Staff/admin `/recharge` | Ticket-bound override; no arbitrary amounts; internal receipt only | Role and public-message isolation tests |
| Explain answer evidence only to admins | Structured summary + factual trace, stored before final reply; API-level visibility | Mock model, role isolation and browser checks |
| Preserve human collaboration | 15-minute priority, 60-second delay, editable final draft and retraction | Workflow and live browser checks |
| Summarize usage/cost | Reported tokens, retries, failures and user-supplied rates; unknown cost stays unknown | Accounting tests and admin UI |

Quota refresh, simulated balance deductions, exact request IDs/time zones, invoice editing and admin-only refund approval remain from v0.5.8. No real payments or live model API calls were made for this release.

Still to measure: new unseen retrieval cases, live-model behavior on the new output schema, production handling time, adoption and cost per resolved ticket. Existing known-question scores do not establish general answer accuracy or financial benefit.
