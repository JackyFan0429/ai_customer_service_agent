# Evaluation

[Home](../README.md) · [Chinese](evaluation.zh-CN.md)

Separate software checks, workflow behavior, retrieval and live-model quality. None is a production resolution rate.

## v0.5.10 evidence

| Layer | Result | Limit |
|---|---|---|
| Software | 292 tests passed | Model API responses are mocked |
| Portal workflow | 29/29 scenarios | Synthetic routes, tools and required facts |
| Legacy RAG, historical v0.5.9 | 48/48 cases, 63/63 turns | Not rerun for this release |
| Reviewed retrieval | 30/30 labels approved; 22 groups | Already published, small synthetic dataset |
| Live model | 12 turns, 34 API calls | Includes pre-fix failures and corrected reruns; known synthetic cases |

[Real-model findings and limits](live-model-acceptance.md) · [Current release evidence](verification.md).

## Retrieval filtering

The scorer stays BM25 0.62 + character 2/3-gram 0.38. The comparison below uses the **same reviewed v3 knowledge and labels**, changing the old top-four coverage filter to subject/capability/exact-identifier filtering. The active-topic parser removes explicitly paused clauses; no LLM query rewrite is used.

| Split | Answerable | Old Recall@4 | Updated Recall@4 | Updated full coverage | Old → updated no-answer false retrieval |
|---|---:|---:|---:|---:|---|
| Development | 17 | 76.47% | 100% | 17/17 | 2/2 → 0/2 |
| Historical holdout diagnostic | 8 | 75% | 100% | 8/8 | 0/1 → 0/1 |

Each split also has one pure dynamic query, reported separately. Updated retrieval returns no static evidence for them. [Development evidence](../evals/releases/v0.5.10/retrieval-development.json) · [Diagnostic evidence](../evals/releases/v0.5.10/retrieval-historical.json).

The development report freezes code/data hashes before the historical holdout run. **Both partitions were already exposed during review and analysis**, so these are regression diagnostics, not a blind generalization result. The filter is specialized to ten built-in policy IDs and high-coverage custom FAQs. New unseen paraphrases and added knowledge require validation.

Recall@4 averages the fraction of required IDs found per answerable query; MRR measures the first relevant rank. Neither grades the final answer. No-answer false retrieval counts returned evidence on questions with no supported knowledge. Current balances and request durations are excluded from those denominators.

The [v0.5.6 method comparison](retrieval-comparison.md) and its frozen corpus remain unchanged. Different labels/knowledge mean its old scores cannot be treated as a direct before/after quality gain.

## Reproduce

From the project root:

```bash
python3 -m pip install -e ".[pdf]"
python3 -m unittest discover -s tests -v
python3 scripts/evaluate_desk.py --as-of '2026-11-04T00:00:00+11:00' --output runtime/desk.json
python3 scripts/evaluate_agent.py --provider local --output runtime/rag.json --fail-on-regression evals/results/after.json
python3 scripts/validate_retrieval_dataset.py --dataset evals/retrieval/lumen-v3 --require-reviewed --output runtime/labels.json
python3 scripts/evaluate_reviewed_retrieval.py development --output runtime/retrieval-dev.json
python3 scripts/evaluate_reviewed_retrieval.py holdout --freeze runtime/retrieval-dev.json --output runtime/retrieval-diagnostic.json
```

Use new output filenames for each retrieval run. The tool refuses existing outputs or a changed freeze fingerprint. PDF dependencies are needed only for the complete test suite, not the website/retrieval evaluator.

## Remaining measurements

Use new unseen questions and a live-model pilot to measure first useful answer time, repeated questions, unsupported claims, human handling time, draft adoption and cost per resolved ticket. Compare equivalent ticket categories and retain failures in denominators.

[Admin usage accounting](admin-evidence.md) now aggregates reported tokens, retries and estimated cost. A normal model answer uses three calls; one content revision can add two. The evidence summary shares composition. Local retrieval avoids an embedding API but does not establish lower total operating cost, labor savings or revenue.
