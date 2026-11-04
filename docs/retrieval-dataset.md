# Reviewed retrieval dataset

[Home](../README.md) · [Chinese](retrieval-dataset.zh-CN.md)

The current [v3 snapshot](../evals/retrieval/lumen-v3) contains **30 owner-approved questions, 22 groups and 10 policy entries**. It separates retrieval labels from the 29-scenario workflow regression. Questions are synthetic; no original customer conversations or credentials are included.

Each label records required knowledge IDs, exact supporting text, rationale, confusing negatives, required/optional business tools and its explicit owner review. All 30 approvals are recorded in [the approval log](../evals/retrieval/lumen-v3/approval-log.json). Policy consultation must not execute an action; a refund request must also query business state; current balance/duration questions cannot be answered by a static rule.

There are 20 development questions in 14 groups and 10 historical holdout questions in 8 groups. Paired paraphrases remain together; different subproblems may reuse a knowledge ID across partitions. These partitions have been published and reviewed, so future checks are diagnostic, not unseen validation.

The latest balance amendment permits rule-checked automatic correction and staff/admin `/recharge`, with private success receipts. Labels and quoted evidence reflect that policy. The original v1 corpus and v0.5.6 experiment are retained unchanged for provenance.

```bash
python3 scripts/validate_retrieval_dataset.py --dataset evals/retrieval/lumen-v3 --require-reviewed --output runtime/reviewed-labels.json
```

Expected: valid structure, 30 approved, zero pending. This validates schema, quotes, references and group boundaries; it does not itself run retrieval or prove answer quality. [Current measurements](evaluation.md).
