# Reproduce the synthetic evaluation

**English** | [简体中文](evaluation.zh-CN.md)

Use the Python environment from the [main tutorial](../README.md#python-demo) and run the following commands from the repository root. No model key or running web server is needed for the local evaluation.

## 1. Run the current version

```bash
python scripts/evaluate_agent.py --output runtime/evaluation.json --fail-on-regression evals/results/after.json
```

Expected: 48/48 complete scenarios, 63/63 complete turns, 14/14 multi-turn scenarios, and an empty `failures` list. Open `runtime/evaluation.json` to inspect individual answers and failed or passed checks.

## 2. Reproduce the earlier implementation

Install Git if it is not already available in your terminal, then run:

```bash
python scripts/reproduce_baseline.py
```

The script applies a checked-in patch in a temporary directory, verifies implementation hashes, runs the same scenarios, and checks the exact baseline metrics and failure IDs. The expected result is **39/48 scenarios**, with nine known failures. The output is `runtime/reproduced_before.json`; your working implementation is not replaced.

The baseline corresponds to the local version before the 2026-09-19 fixes, which had 40 software tests. It is not the earlier remote version with 38 tests. After anonymization, both implementations were rerun against `synthetic-v2-neutral`. Names can affect lexical retrieval, so reports and hashes were regenerated from executions. Both sets of acceptance counts remained unchanged.

## 3. Understand what is measured

The dataset has 48 synthetic development scenarios, 63 messages, and 14 multi-turn scenarios, using 19 fictional knowledge records. Labels were AI-authored and await owner review. These tasks were visible during development; this is neither a held-out test nor a sample of real traffic.

Each line in `evals/scenarios.jsonl` contains the scenario ID, category, origin, label status, knowledge version, fixed date, selected `corpus_ids`, and ordered `turns`. Each turn specifies a query, expected route, required and allowed evidence IDs, necessary answer points, and forbidden conclusions.

For `required_points`, the outer list is AND and each inner list is OR. Lexical checks may misread negation or complex wording and do not replace factual review. Each scenario gets its own session. Any failed turn fails the whole scenario; exceptions stay in the denominator. The evaluation date is fixed at 2026-09-19. Far-future review dates are fictional test fixtures only.

| Metric | Numerator / denominator |
| --- | --- |
| `scenario_pass` | Scenarios where every turn passes / all scenarios. |
| `turn_pass` | Turns passing route, content, forbidden-conclusion and evidence checks / all turns. |
| `route_accuracy` | Turns routed as labeled / all turns. |
| `answerable_acceptance` | Fully passing answerable knowledge turns / turns labeled answer with expected evidence. |
| `evidence_rule_violation` | Cited answers with evidence outside the allowed set / all cited answers. |
| `escalation_recall` | Correct escalations / turns labeled escalate. |
| `multi_turn_success` | Fully passing multi-turn scenarios / all multi-turn scenarios. |

`evidence_rule_violation` only checks evidence IDs; it is not a hallucination rate. Unsupported conclusions can occur even with correct citations. Claim-level human review or a calibrated judge is a separate requirement.

Reports preserve per-turn output, failures, implementation-file hashes, and hashes of the corpus, scenarios, and grading script. `elapsed_ms` is local execution time, not model latency. Unmeasured API cost and tokens are `null`, not zero.

## 4. Compare the recorded results

| Metric | Before | After |
| --- | --- | --- |
| Complete scenarios | 39/48 | 48/48 |
| Complete turns | 53/63 | 63/63 |
| Correct routes | 56/63 | 63/63 |
| Answerable-turn acceptance | 29/33 | 33/33 |
| Evidence-set violations | 3/32 | 0/33 |
| Required escalations recalled | 9/9 | 9/9 |
| Multi-turn scenarios | 9/14 | 14/14 |

The nine previously failing scenarios cover general refund-policy questions incorrectly escalated, confusion between 401/1401, 401/E401 and E401/E4012, short error-code updates, and unresolved follow-ups that lost their topic. None of the previously passing 39 scenarios regressed.

Changing scenarios, corpus, grader, provider, or fixed dates invalidates the same-condition comparison. The comparison command rejects mismatched inputs. Establish a new baseline for intentional changes rather than removing failures from the denominator or silently overwriting earlier evidence. Source files use LF line endings to keep hashes consistent across checkouts.

## 5. Keep software tests separate

```bash
python -m pip install -e ".[pdf]"
python -m unittest discover -s tests -v
```

Expect 59 software tests. They also cover web-session restoration, isolation, standalone-query generation, identifier preservation, evidence-budget alignment, and date-sensitive checks. API tests use mocks. Neither this suite nor the stored local reports are a real-model end-to-end evaluation or evidence of a production resolution rate.
