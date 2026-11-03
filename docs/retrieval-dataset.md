# Retrieval dataset

[Documentation](README.md) · [Chinese](retrieval-dataset.zh-CN.md)

Dataset `lumen-retrieval-v1`, introduced in v0.5.5: **30 synthetic queries**, **10 knowledge entries**, **22 business subproblem groups**. It evaluates retrieval separately from the 29 portal workflow scenarios.

All labels are AI-assisted and marked `pending_owner_review`. “Independent” means a separate retrieval evaluation task, not an external gold-standard benchmark. v0.5.6 has since run the [method comparison](retrieval-comparison.md).

## Split and denominators

| Query type | Development | Holdout | Scoring |
|---|---:|---:|---|
| Static knowledge answerable | 15 | 7 | Recall and MRR |
| Knowledge plus business data | 2 | 1 | Static evidence only |
| No knowledge answer | 2 | 1 | False retrieval |
| Pure business-data query | 1 | 1 | Separate diagnostic |
| **Total** | **20** | **10** | Report each split separately |

Recall/MRR denominators are **17** and **8**, not 20 and 10. A current-balance question cannot be treated as a failed static-knowledge query.

The split uses business subproblem groups: 14 development groups and 8 holdout groups. Paired paraphrases stay together. A knowledge entry can support different subproblems across splits. The validator checks group overlap and normalized exact duplicates; semantic near-duplicates still need review.

## Annotation

Each query records relevant knowledge IDs, exact evidence excerpts, rationale, confusing negative examples, required read tools and review status. A positive must directly support the current question. A shared model name or topic alone is insufficient. Multi-part queries include every necessary source.

Labels were assigned from the complete knowledge snapshot, not from the retriever's rankings. Evidence substring checks establish provenance, not semantic sufficiency.

[Development JSONL](../evals/retrieval/lumen-v1/development.jsonl) · [Holdout JSONL](../evals/retrieval/lumen-v1/holdout.jsonl) · [Knowledge](../evals/retrieval/lumen-v1/knowledge.json) · [Manifest](../evals/retrieval/lumen-v1/manifest.json)

## Validate

```bash
python3 scripts/validate_retrieval_dataset.py
```

Expected: `valid: true`, 30 queries, 22 groups and 30 pending reviews. Output: `runtime/retrieval_dataset_validation.json`.

```bash
python3 scripts/validate_retrieval_dataset.py --require-reviewed --output runtime/retrieval-review-gate.json
```

The second command deliberately fails while labels await review. Record real reviewer approval only after review. Changes to labels, knowledge or split require a new dataset version and hashes; keep old evidence intact.

## Scope

Queries use the complete corpus at a fixed business time, `2026-11-03T13:00:00+00:00`, with a review deadline of `2027-02-01`. This tests lexical retrieval, not expiry handling, automatic query rewriting, conversation state or generated answer quality.

Holdout files are distributed openly. The published v0.5.6 results are no longer unseen; if they guide a future change, use a new final validation set.

