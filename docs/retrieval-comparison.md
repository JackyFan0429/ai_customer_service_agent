# BM25, character n-grams and hybrid retrieval

> Historical v0.5.6 experiment. For reviewed v3 labels and v0.5.9 filtering, see [current evaluation](evaluation.md). All results below keep their original corpus and label status.

[Documentation](README.md) · [Chinese](retrieval-comparison.zh-CN.md)

Experiment: **v0.5.6**, 4 November 2026, using the frozen v0.5.5 dataset. This release preserves the original reports.

**The main bottleneck was coverage filtering.** Relevant entries reached the raw candidate set but were removed before generation. All three methods produced identical final rankings on this dataset; this does not establish that hybrid is better than BM25.

## Results

| Split | Method | Final Recall@4 | Final MRR@4 | Raw Recall@4 | Raw MRR@4 |
|---|---|---:|---:|---:|---:|
| Development | BM25 | 67.65% | 70.59% | 100.00% | 92.65% |
| Development | Character n-grams | 67.65% | 70.59% | 88.24% | 79.41% |
| Development | Hybrid | 67.65% | 70.59% | 100.00% | 92.65% |
| Holdout | BM25 | 68.75% | 75.00% | 100.00% | 91.67% |
| Holdout | Character n-grams | 68.75% | 75.00% | 87.50% | 79.17% |
| Holdout | Hybrid | 68.75% | 75.00% | 100.00% | 91.67% |

Final full coverage: **11/17** development queries and **5/8** holdout queries. Final false retrieval on no-answer queries: **0/2** and **0/1**; all had nonempty raw candidates. Retrieval exceptions: 0.

Recall averages the relevant fraction per query. Final precision over actual returned entries averaged **59.80%** and **62.50%**. Irrelevant evidence still accompanied 4 development answers and 2 holdout answers. No customer answers were generated in this experiment.

## Shared configuration

| Component | Fixed setting |
|---|---|
| Corpus | Same complete 10-entry snapshot for every query |
| Query | Full query text; no labels, correct IDs or rewriting appended |
| BM25 | `k1=1.5`, `b=0.75`; normalized by maximum query score |
| Character score | Cosine similarity of character bigram/trigram counts; no embeddings |
| Weights | BM25 `(1,0)`; characters `(0,1)`; hybrid `(0.62,0.38)` |
| Business rules | Same source weighting and priority rules; corpus order breaks ties |
| Candidate/filter | Top 4, then coverage ≥ 0.12; no refill from lower ranks |

This is an ablation inside the existing support retrieval pipeline, not an unrestricted comparison of pure algorithms. Both base scores are computed for diagnostic reporting, so timing cannot establish deployment speed or cost advantages.

## Development diagnosis and selection

BM25/hybrid retrieved six required development evidence items that coverage filtering subsequently removed. Examples include colloquial references to quota versus wallet balance, small-debt correction, refund requests and failed-request charges. A combined refund/quota query retained only one of two required sources.

Character-only scoring additionally missed two required items before filtering. Sparse n-grams do not automatically equate business synonyms. Removing the coverage threshold would also admit the observed no-answer candidates, so no threshold or knowledge change was made.

The predefined selection order was: no retrieval exceptions, higher Recall, lower no-answer false retrieval, then higher MRR. A tie retains the existing hybrid. **No parameter search was performed.**

## Freeze, then holdout

The freeze was recorded at **2026-11-03 16:17:07 UTC**, before the holdout run, with data, code and configuration hashes. The holdout retained the development choice; `selection_updated_from_holdout` is `false`.

Three required holdout items reached BM25/hybrid Top-4 and were filtered out, consistent with development failures. Results were not used to retune. Labels remain AI-assisted and pending owner review. The now-published holdout cannot be reused as unseen validation after designing fixes from its failures.

[Development report](../evals/retrieval/experiments/v0.5.6/development.json) · [Freeze](../evals/retrieval/experiments/v0.5.6/frozen.json) · [Holdout report](../evals/retrieval/experiments/v0.5.6/holdout.json)

## Reproduce in order

```bash
python3 scripts/evaluate_retrieval.py development
python3 scripts/evaluate_retrieval.py freeze --development-report runtime/retrieval/development.json --rationale "Reproduce released settings; development tie retains hybrid; no tuning"
python3 scripts/evaluate_retrieval.py holdout --freeze runtime/retrieval/frozen.json
```

Inspect development results before freezing. Commands refuse to overwrite existing reports: use new `--output` paths and pass those paths to subsequent steps. Holdout execution requires matching data, code and parameter hashes.

This experiment made **zero external model calls**. It does not measure answer quality, customer wait time, retry reduction or per-ticket cost. Improving evidence coverage is a hypothesis to validate in the full workflow, not a measured business benefit.

