# Evaluation

[Home](../README.md) · [Chinese](evaluation.zh-CN.md)

Keep software checks, workflow acceptance, retrieval quality and live-model behavior separate. None is a production resolution rate.

## Current evidence

| Layer | Dataset / result | Limitation |
|---|---|---|
| Software tests | 225 passed in v0.5.7 | API responses are mocked |
| Portal workflow | 29/29 synthetic scenarios | Checks routes, required tools and fact fragments |
| Legacy RAG | 48/48 scenarios; 63/63 turns | Development regression, not unseen traffic |
| Retrieval | 20 development + 10 holdout queries; 10 knowledge entries | AI-assisted labels await owner review |
| Historical live model | v0.5.3: 8 post-fix turns, 22 successful API calls, no fallback | Small historical sample; not rerun for v0.5.7 |

Of the 8 historical turns, 7 used model answers and 1 used a controlled business template. Call counts therefore differ from turn counts. [Raw record](topic-switch-live-v0.5.3.json).

## Reproduce local checks

The portal and retrieval checks need only Python 3.11+. The full software suite also tests PDF extraction, which requires the optional PDF dependency.

```bash
python3 -m pip install -e ".[pdf]"
python3 -m unittest discover -s tests -v
python3 scripts/evaluate_desk.py --as-of '2026-11-04T00:00:00+11:00' --output runtime/desk-evaluation.json
python3 scripts/evaluate_agent.py --provider local --output runtime/rag-evaluation.json --fail-on-regression evals/results/after.json
python3 scripts/validate_retrieval_dataset.py
```

Run from the project root. Outputs go to `runtime/`; packaged release evidence stays under `evals/`. A successful dataset validation confirms references, grouping and schema, not retrieval success or human approval.

For retrieval experiments, use the development → freeze → holdout sequence in the [comparison guide](retrieval-comparison.md). Frozen v0.5.6 results remain unchanged in this release; no new holdout tuning was performed.

## Metric definitions

- **Recall@4:** per-query fraction of required knowledge IDs retrieved, averaged over knowledge-answerable queries. A two-source question returning one source scores 0.5.
- **MRR@4:** reciprocal rank of the first relevant result. It does not prove all subquestions have evidence.
- **No-answer false retrieval:** no-answer queries with any returned evidence / all no-answer queries.
- **Pure dynamic queries:** reported separately; static knowledge cannot establish a current balance or request duration.
- **Workflow acceptance:** required routing, tools and fact checks. It is not claim-level answer grading.

Final retrieval metrics tie across BM25, character n-grams and hybrid:

| Split | Answerable denominator | Recall@4 | MRR@4 | Fully covered | No-answer false retrieval |
|---|---:|---:|---:|---:|---:|
| Development | 17 | 67.65% | 70.59% | 11/17 | 0/2 |
| Holdout | 8 | 68.75% | 75.00% | 5/8 | 0/1 |

The dataset is small and provisional. One correctly rejected holdout negative does not establish a low general hallucination rate. [Method details and failure analysis](retrieval-comparison.md).

## Remaining measurements

1. Review labels and missing evidence with the project owner; retain versioned label changes.
2. Improve coverage filtering on development examples, then use new unseen validation queries if published holdout cases inform the changes.
3. Aggregate model usage, retries, latency and provider prices. Unknown cost stays unknown, not zero.
4. In a real deployment, measure time to first useful answer, repeated-question rate, human handling time, draft adoption and cost per resolved ticket.

A typical model reply uses three calls; a revision may add two. Local retrieval needs no embedding API, but that alone does not establish lower total cost. No measured revenue or labor savings are claimed.

The [legacy evaluation](legacy/evaluation.md) retains the 2026-09-19 before/after reports. Reconstructing that old implementation requires a matching historical source snapshot; the current source is not an interchangeable substitute.

