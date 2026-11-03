# Knowledge sources

[Home](../README.md) · [Chinese](README.zh-CN.md)

| Scope | Included source |
|---|---|
| Current portal | `support_agent/desk/data/knowledge.json`: 10 synthetic policies, loaded into SQLite on initialization |
| Legacy RAG | `support_agent/demo/corpus.jsonl`: 19 synthetic records |
| Retrieval evaluation | `evals/retrieval/lumen-v1/knowledge.json`: frozen portal snapshot, retained for reproducibility |

Portal knowledge is managed in the admin console. The [legacy import pipeline](../docs/legacy/operations.md) produces a separate JSONL corpus; it does not automatically update the portal.

Real company documents are not included. The ignore rules cover `knowledge/official/internal/`, `sources/` and `audit/`, **not the entire `knowledge/official/` directory**. Keep private material in explicitly ignored locations. The release packager includes only these two knowledge guides, not private source folders.

Record source references, actual verification dates and expiry. [Source policy](../docs/legacy/official_kb_policy.md).

