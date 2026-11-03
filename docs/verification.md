# Release verification

[Documentation](README.md) · [Chinese](verification.zh-CN.md)

## v0.5.7 — documentation and packaging

Built independently from the v0.5.6 release ZIP on 4 November 2026. The portal, model integration, knowledge, retrieval implementation and frozen experiment results are unchanged.

Changes:
- Rewrote bilingual quick starts and guides; added local SVG language buttons and linked technology/test badges.
- Separated current portal documentation from legacy RAG and historical release notes.
- Corrected the old baseline-reconstruction command: it now requires a matching historical source snapshot and checks hashes before applying a patch.
- Extended release exclusions for caches, environment files, database sidecars and editor backups; retained required fixtures and audit evidence.

| Check | Result | Evidence |
|---|---|---|
| Software suite | **225 passed**, Python 3.12 | [Full output](../evals/releases/v0.5.7/tests.txt) |
| Portal workflow | **29/29 scenarios** | [Report](../evals/releases/v0.5.7/desk-workflow.json) |
| Legacy RAG | **48/48 scenarios, 63/63 turns**, no baseline regression | [Report](../evals/releases/v0.5.7/legacy-rag.json) |
| Dataset validation | **30 queries / 22 groups**, all pending owner review | [Report](../evals/releases/v0.5.7/dataset-validation.json) |

Seven added checks cover packaging boundaries and historical-source validation. The old implementation itself was not reconstructed: the required historical source is not included.

No external model calls or Docker build were made for this release. Local API tests use simulated responses. The v0.5.6 holdout was not rerun or used to change parameters.

## Historical evidence

| Version | Focus | Record |
|---|---|---|
| v0.5.6 | BM25, character n-gram and hybrid comparison | [Analysis](retrieval-comparison.md), [frozen results](../evals/retrieval/experiments/v0.5.6) |
| v0.5.5 | Independent retrieval dataset and grouped split | [Dataset](retrieval-dataset.md) |
| v0.5.4 | Reproducible workflow and legacy baselines | [Baseline manifest](../evals/baselines/lumen-v0.5.3-2026-11-04/manifest.json) |
| v0.5.3 | Quota, balance and configuration topic switching | [Live-model record](topic-switch-live-v0.5.3.json) |
| v0.5.2 | Follow-ups, refunds and human context | [Live-model record](multiturn-live-v0.5.2.json) |

The [historical verification archive](history/verification-through-v0.5.6.zh-CN.md) is in Chinese and preserves earlier screenshots and observations. Historical live-model success is not a new API verification for this release.

Open work: owner review of retrieval labels, coverage-filter improvements and model-usage/cost summaries. [Measurement plan](evaluation.md#remaining-measurements).

