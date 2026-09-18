# Architecture

**English** | [简体中文](architecture.zh-CN.md)

This personal prototype is a program-orchestrated retrieval-augmented support workflow. It does not have live business tools or an autonomous planning loop. Start with the [step-by-step demo](../README.md#python-demo).

```text
Offline: historical cases → rule-based classification and quality tiers
        → official-source checks → conflict flags → retrieval corpus

Online: customer message + the latest 8 conversation messages
      → local rules / structured model understanding
      → standalone query (replace old topics and outdated error codes)
      → BM25 + character n-gram retrieval
      → identifier, relevance, expiry, conflict and audience checks
      → apply a shared evidence-text budget
      → answer: generate from the standalone query and selected evidence
        clarify: ask for details, retaining the active unresolved topic
        escalate: request human verification without executing a ticket action
      → SQLite for web conversations; process-local memory for the CLI
```

| Module | Responsibility |
| --- | --- |
| `session.py` | Bounded history; infer local context from user messages, not error codes mentioned by the assistant. |
| `providers.py` | Local extraction and rules; structured understanding and generation through the Responses API. |
| `retrieval.py` | BM25 and character bigram/trigram cosine similarity; complete identifier matching. |
| `policy.py` | Source expiry, conflicts, audience filtering, account-specific and live-status escalation. |
| `prompts.py` | Pass untrusted content as data; enforce a shared evidence-text budget. |
| `agent.py` | Orchestration, preservation of explicit identifiers, and alignment of evidence with citations. |
| `database.py` / `web.py` | SQLite persistence, HTTP endpoints, and the page. |
| `scripts/evaluate_agent.py` | Fixed-date, per-turn acceptance checks and scenario comparisons. |
| `scripts/review_knowledge.py` | Review deadlines and pending verification queues. |

## Evidence precedence

P0 live tools are not connected. P1 represents official knowledge within its review window. P2 historical cases only provide troubleshooting clues. P3 low-confidence or unresolved material does not enter the primary retrieval corpus. The packaged P1/P2 records are fictional role fixtures, not real policies.

`restricted_internal` material should be excluded when building a corpus and is also rejected at response time. The bodies of `agent_internal` records are not given to the model or customer; the workflow currently retains only candidate IDs for internal routing signals.

## Limits to verify when extending the demo

Local rules cover a narrow set of short error-code changes and unresolved follow-ups. Long conversations can lose context beyond the message window; complex ellipsis and corrections need additional evaluation. Model understanding needs its own live-model evaluation. Ranking weights and top-K have not been tuned on production traffic.

Citations identify material visible during generation. The local provider cites the record it actually renders; this does not establish support for every possible generated claim. Evidence budgets count text characters, not tokens.
