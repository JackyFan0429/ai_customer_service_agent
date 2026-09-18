# Response policy and data boundaries

**English** | [简体中文](safety.zh-CN.md)

To observe the policy in practice, run the [five-message demo](../README.md#demo-conversation), then inspect the structured CLI output or [evaluation results](evaluation.md).

## Data boundaries

Customer queries and retrieved knowledge are treated as untrusted data. Instructions embedded in those records must not be executed. The assistant must not request passwords, API keys, complete payment receipts, or other secrets. Private source documents, derived records, and customer data are excluded by `.gitignore`; the public demo contains only synthetic records.

## Evidence eligible for a customer answer

- P1 records with audience `customer_safe` that are still within `review_after`.
- P2 historical cases with `conflict_status=no_rule_conflict_detected`, used only as troubleshooting clues.

Bodies of `agent_internal` records, `restricted_internal` records, expired P1 documents, and conflicting or potentially outdated P2 cases are excluded from model evidence and customer citations.

## Human review

Account-specific requests about orders, balances, refunds, charges, ownership, or live service state require a live tool or human authority. The prototype must not claim to have queried those systems or promise refunds, compensation, quota, or recovery deadlines. General policy questions can still be answered when eligible evidence exists.

Escalation only returns a route and a message. It does not create or assign a real ticket.

## Citations

The orchestration layer creates citation metadata from evidence actually provided to the generator. The local provider cites the first record it renders; the model provider cites the policy-filtered context. This avoids letting a model invent citation IDs, but does not verify each sentence against its source.

## Failure behavior

| Condition | Response |
| --- | --- |
| Insufficient evidence | Ask for the product, client, steps and full redacted error. |
| Live facts unavailable | Explain the static knowledge limitation and request human verification. |
| Model API failure | Return an error to the channel layer; a production integration would need a fallback. |
| Internal or restricted material | Exclude the text; retain only permitted internal routing signals. |

The web server has no authentication and is intended for local demonstrations. Both native startup in the tutorial and Compose publish the demo on loopback by default.
