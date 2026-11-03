# Legacy evaluation

[Legacy guide](README.md) · [Chinese](evaluation.zh-CN.md)

## Current regression

```bash
python3 scripts/evaluate_agent.py --provider local --output runtime/evaluation.json --fail-on-regression evals/results/after.json
```

The included corpus has 19 synthetic entries. The development set has 48 scenarios, 63 turns and 14 multi-turn scenarios; labels are AI-authored and await owner review. Expected current result: **48/48 scenarios and 63/63 turns**.

Checks cover routes, required/allowed evidence IDs, necessary answer points and forbidden conclusions. Any failed turn fails its scenario; exceptions remain in the denominator. The evaluation date is fixed at 2026-09-19. Matching evidence IDs is not claim-level factual validation.

## Historical comparison

| Metric | Before | After |
|---|---:|---:|
| Complete scenarios | 39/48 | 48/48 |
| Complete turns | 53/63 | 63/63 |
| Correct routes | 56/63 | 63/63 |
| Multi-turn scenarios | 9/14 | 14/14 |
| Required escalations recalled | 9/9 | 9/9 |

[Before report](../../evals/results/before.json) · [After report](../../evals/results/after.json) · [Historical patch](../../evals/baselines/pre_iteration.patch)

The historical fixes addressed general refund-policy routing, similar error identifiers and lost follow-up context. These development results do not measure production impact.

## Reconstructing the old source

The patch expects the exact **2026-09-19 post-fix source snapshot**, which is not bundled. Current sources have since changed. If you possess that matching snapshot:

```bash
python3 scripts/reproduce_baseline.py --source-root /path/to/matching-historical-source
```

The script validates the recorded source hashes before applying the patch in a temporary directory, then verifies the earlier hashes and outcomes. Missing or mismatched sources stop immediately. The public package alone cannot recreate the old implementation from today's source; use the current regression command above.

Input, grader and corpus hashes govern report comparisons. Changed inputs require a new baseline. Local elapsed time is not model latency, and unmeasured tokens/cost are `null`, not zero. For the full current test suite, see [evaluation](../evaluation.md).

