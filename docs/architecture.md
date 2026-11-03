# Architecture

[Home](../README.md) · [Chinese](architecture.zh-CN.md)

The current portal is a Python-orchestrated support workflow with a SQLite business database and JavaScript UI. The model cannot freely choose or execute database writes.

```text
Customer message + recent public conversation
  → topic tracking and triage
  → scoped business queries + knowledge retrieval
  → compose from current evidence
  → content / action checks
  → automatic reply, clarification, private suggestion or human handoff
  → persist state → SSE notification → clients fetch authorized current data
```

## Evidence and actions

Ten read tools cover account overview, subscriptions, orders, invoices, recent requests, platform status, API-key metadata, ticket history, balance-correction eligibility and knowledge search. Queries are scoped to the customer associated with the ticket.

The model proposes structured decisions and wording. Python controls allowed queries, fact checks and sending. Protected writes run through application services and role checks: support can reply and retract; admins manage account, plan, balance and global AI settings. Financial state is simulated locally.

## Knowledge and retrieval

The portal starts with **10 synthetic policy entries** in `support_agent/desk/data/knowledge.json`. Each is a complete rule or FAQ with its own ID and metadata. These are curated units, not fixed-length text windows.

The separate legacy pipeline has **19 synthetic records**. Its PDF importer groups content by numbered third-level headings and keeps FAQ units together. It does not automatically replace the portal knowledge table. [Knowledge scope](../knowledge/README.md).

The shared retriever combines normalized BM25 (**0.62**) with character bigram/trigram cosine similarity (**0.38**). BM25 uses `k1=1.5`, `b=0.75` and lexical features including Chinese characters/bigrams and English identifiers. Character similarity is sparse lexical matching, not an embedding model.

The portal ranks candidates, takes up to **4**, then requires query coverage **≥ 0.12**. Rejected entries are not replaced from lower ranks. Source metadata and priority rules also influence ranking. A character budget bounds evidence sent to the model; it is not a token-cost estimate. [Method comparison](retrieval-comparison.md).

## Conversation and collaboration

- The model sees up to **24 prior public messages**, bounded at approximately **16,000 characters**, including customer, AI and human replies. Truncation is marked.
- Retracted text, private suggestions, internal notes and other customers' conversations are excluded.
- Topic tracking separates paused issues from the current question. Returning to a previous issue triggers fresh business queries; ambiguous references can require clarification.
- A human reply gives **15 minutes** of priority. An unanswered customer follow-up waits **60 seconds** before a private suggestion is generated. Explicit takeover lasts until staff resume AI.
- New customer input invalidates older pending suggestions. Automatic sending still depends on the global switch, current ticket state, checks and action approval.

## Model integration

Local mode uses rules and templates. Optional Chat Completions or Responses access uses structured triage, composition and review: ordinarily **3 calls**. A content revision can add **2** more calls. Composition and review receive the same current evidence and conversation context.

Startup checks all three stages. Runtime diagnostics distinguish API failure, rejected content and local fallback, retaining model names and sanitized reasons. No model weights are trained.

## Module map

| Path | Responsibility |
|---|---|
| `support_agent/portal.py` | HTTP routes, sessions, authorization and SSE |
| `support_agent/desk/service.py` | Tickets, background generation, human priority and sending |
| `support_agent/desk/engine.py` | Triage, evidence orchestration and reply checks |
| `support_agent/desk/topics.py` | Active topic and follow-up handling |
| `support_agent/desk/tools.py` | Customer-scoped read tools and knowledge filtering |
| `support_agent/desk/model.py` | Model prompts, composition and review |
| `support_agent/desk/storage.py` | SQLite schema, migrations and synthetic fixtures |
| `support_agent/desk/admin.py` | Controlled account, plan, balance and knowledge changes |
| `support_agent/retrieval.py` | Shared BM25 and character scoring |
| `support_agent/desk/static/` | Portal UI and live synchronization |

[Earlier standalone RAG architecture](legacy/architecture.md) describes a different entrypoint without the business portal.

