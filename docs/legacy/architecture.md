# Legacy RAG architecture

[Legacy guide](README.md) · [Chinese](architecture.zh-CN.md)

This page applies only to `support_agent.web` and `support_agent.cli`. For the business portal, see [current architecture](../architecture.md).

```text
Message + latest 8 conversation messages
  → local / structured model understanding
  → standalone query, preserving exact identifiers
  → BM25 + character n-gram retrieval
  → relevance, expiry, conflict and audience checks
  → bounded evidence text
  → answer / clarify / escalate
```

| Module | Responsibility |
|---|---|
| `session.py` | Bounded history and active unresolved topic |
| `providers.py` | Local rules or model understanding/generation |
| `retrieval.py` | Shared lexical ranking and exact identifiers |
| `policy.py` | Source validity, disclosure and escalation |
| `prompts.py` | Evidence-text budget and untrusted-data boundaries |
| `agent.py` | Orchestration and citation metadata |
| `database.py`, `web.py` | Standalone conversation storage and HTTP UI |

P1 represents reviewed source knowledge, P2 historical troubleshooting clues, and P3 unresolved material. Packaged records simulate these roles. This entrypoint has no live business tools; an escalation is a route/message, not a ticket action.

Internal/restricted text is excluded from customer evidence. Citations identify supplied records but do not prove every generated claim. Evidence budgets count characters, not tokens. The current [retrieval comparison](../retrieval-comparison.md) evaluates portal filtering, not this complete legacy response pipeline.

