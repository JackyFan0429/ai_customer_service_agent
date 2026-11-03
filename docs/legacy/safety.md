# Legacy response policy

[Legacy guide](README.md) · [Chinese](safety.zh-CN.md)

This policy describes the standalone RAG entrypoint. The current portal adds authorized business tools and approval controls.

Queries and retrieved text are untrusted data. The model must not follow instructions embedded in them or request passwords, API keys or complete payment receipts.

Customer evidence may include current `customer_safe` P1 entries and nonconflicting P2 troubleshooting clues. Restricted material, internal bodies, expired sources and conflicting cases are excluded. Citation metadata is derived from supplied records; it is not a sentence-level fact checker.

| Condition | Legacy behavior |
|---|---|
| Insufficient evidence | Request relevant details |
| Account-specific action or current service state | Escalate for verification; no business tool is connected |
| Model API failure | Return an error to the channel |
| Internal/restricted text | Exclude it from customer evidence |

Escalation does not create a ticket. The standalone server has no authentication; use loopback for the demo. The [current portal](../architecture.md) has different permissions and fallback behavior.

Private source directories are excluded only as specified in `.gitignore` and `.dockerignore`; do not assume every file under `knowledge/official/` is ignored. [Data scope](data_scope.md).

