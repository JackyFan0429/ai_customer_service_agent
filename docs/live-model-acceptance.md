# Real-model acceptance: v0.5.10

[Documentation](README.md) · [Chinese](live-model-acceptance.zh-CN.md)

On 5 November 2026 (Australia/Sydney), tested **12 turns and 34 recorded API calls** using the owner's `gpt-6-astra` configuration through Chat Completions. The provider also reported `gpt-6-astra`. Business records and charges were local synthetic data. [Run evidence](../evals/releases/v0.5.10/live-model.json).

## Findings and fixes

| Finding | Change | Verification |
|---|---|---|
| Error codes attached to Chinese text lost their knowledge match; short 403 follow-ups omitted the plan policy. | Match complete numeric identifiers without treating Chinese as an identifier boundary. Include the plan policy dependency for 403 and balance-fallback questions. | Topic switch and return tests retrieve ERR-401 + PLAN-001; 1401/1403 are not treated as 401/403. |
| A correct negative balance written as `-$7`, followed by a $7 debt amount, triggered a local monetary check and fallback. | Preserve the currency sign; permit a debt magnitude only when the current queried negative balance supports it. | The same rejected scenario now uses three calls instead of five and stays on the real model. Tests still reject invented positive balances, refund amounts, stale debt and currency mismatches. |
| The admin receipt labelled a deliberate financial template as local, which resembled a model failure. | Distinguish real-model answers, financial templates and actual fallback, including successful model triage. | Eligible corrections use real triage plus the fixed transaction template, with no false claim of model-written financial confirmation. |

## Accepted flows

- Combined error/plan and refund/plan knowledge; paused topics stay out of the answer.
- Admin-only receipts list actual knowledge and queries. Support and customer APIs omit them; personal admin mode also loses workbench access.
- Small eligible debt and the first eligible $6 debt are cleared once. A later $7 debt within seven days is blocked. Staff `/recharge` overrides eligibility and emits only an internal receipt.
- After a human reply, the customer waits 60 seconds before an internal suggestion is generated. The model reuses client/model/setup details. Customer delivery happens only after staff sends it.
- Restoring AI uses the updated Key setting, exact request #37 and current $18.38 balance, not the earlier $18.50 snapshot. Send and retract changes appear without a manual page refresh.

The investigative set contains one pre-fix fallback and two pre-fix knowledge omissions; their corrected reruns are retained separately. This is not a claim that every initial run passed. Normal answer generation uses triage, composition and review; eligible financial writes use a fixed template after triage. The admin evidence summary shares the composition call.

## Reproduce

Start a separate copy with `python3 scripts/start_demo.py --provider openai`, enter your endpoint, hidden key, model and protocol, then use the demo accounts in the [quick start](../README.md#quick-start). The [JSON report](../evals/releases/v0.5.10/live-model.json) retains exact synthetic questions, retrieved evidence and observed outputs. The $6/$7 cases require isolated ledger fixtures; they were not real charges.

No provider tariff was supplied, so token usage is recorded without a currency estimate. The reduction from five calls to three applies to the repaired scenario only. Startup probes are excluded from the totals. No production savings, blind accuracy or other-model compatibility is claimed.
