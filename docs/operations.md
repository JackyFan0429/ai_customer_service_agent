# Local operation and knowledge maintenance

**English** | [简体中文](operations.zh-CN.md)

Start with the [main tutorial](../README.md). The first three steps below use only included synthetic data. Run commands from the repository root with the Python environment activated.

## 1. Make a separate demo corpus

Copy the packaged corpus to a working file:

```bash
python -c "from pathlib import Path; import shutil; Path('runtime').mkdir(exist_ok=True); shutil.copyfile('support_agent/demo/corpus.jsonl', 'runtime/copied_demo.jsonl')"
```

Expected: `runtime/copied_demo.jsonl` contains the same 19 fictional records. Edit this working copy when experimenting, keeping the checked-in corpus unchanged for baseline comparisons.

## 2. Run against that file

```bash
python -m support_agent.web --provider local --host 127.0.0.1 --port 8081 --corpus runtime/copied_demo.jsonl --database runtime/custom_demo.db
```

Open [http://127.0.0.1:8081](http://127.0.0.1:8081) and send `ClientA Base URL 怎么配置？`. Expect a fictional setup answer. The copied records retain `synthetic: true`, so the header still labels them as demo data. This command uses a separate database. Press Ctrl+C to stop the server.

CLI alternative:

```bash
python -m support_agent.cli --provider local --corpus runtime/copied_demo.jsonl --json "ClientA Base URL 怎么配置？"
```

Web sessions persist in SQLite; CLI history stays in process memory. The web server is a local prototype without authentication. If installed with `pip install -e .`, the console entry points are `support-agent` and `support-agent-web`.

## 3. Generate a review queue

```bash
python scripts/review_knowledge.py --corpus runtime/copied_demo.jsonl --as-of 2026-09-19 --output runtime/demo_knowledge_review
```

Open `runtime/demo_knowledge_review/summary.json` and `review_queue.jsonl`. Some fixtures intentionally simulate outdated sources. The queue records source references, content hashes, review reasons, and fields for reviewer, date and supporting evidence. It does not renew facts or modify the input corpus. Far-future dates in the other synthetic records are for reproducible demonstrations, not real policy management.

## 4. Optional: prepare your own private inputs

This section is a workflow reference, **not a command sequence that can run from the public demo alone**. Supply your own redacted cases and source documents first. Original business data is not included.

- Normalize cases to `data/input/case_kb_preview/canonical_cases.jsonl`. Each message must have `message_id`, `role`, and `content`; map channel-specific IDs to `message_id` before processing.
- Configure product/client rules in `scripts/enrich_cases.py` and `scripts/extract_pdf_official_kb.py`. Their current labels are fictional examples.
- Prepare source-attributed official JSONL records under `knowledge/official/` using the [official schema](official_kb_policy.md). Keep the full directory private.
- Install PDF dependencies with `python -m pip install -e ".[pdf]"` if you will extract a PDF.

Enrich your normalized cases:

```bash
python scripts/enrich_cases.py --input data/input/case_kb_preview/canonical_cases.jsonl --output data/output/enriched
```

If extracting a PDF, replace the sample filename and snapshot date with your actual file and extraction date:

```bash
python scripts/extract_pdf_official_kb.py --input knowledge/official/sources/support_knowledge_base.pdf --snapshot-date 2026-09-19 --output knowledge/official/internal/support_internal_pdf.jsonl --audit knowledge/official/audit/support_internal_pdf_audit.json --report knowledge/official/audit/support_internal_pdf_report.json
```

`snapshot-date` is the extraction date, not proof that policies are current. Without `--verified-at`, extracted records intentionally expire before the snapshot and await source verification. Only provide a verification date after genuinely reviewing the corresponding policies. A document with mixed validity needs record-level review rather than blanket renewal. Back up prior extraction outputs before replacing them.

## 5. Build and validate a private corpus

After preparing and reviewing the required inputs:

```bash
python scripts/ingest_official_kb.py --input knowledge/official --output data/output/official_kb
python scripts/check_case_conflicts.py --cases data/output/enriched/case_summaries.jsonl --official-kb data/output/official_kb/official_kb.jsonl --output data/output/conflicts
python scripts/build_retrieval_corpus.py --official-kb data/output/official_kb/official_kb.jsonl --cases data/output/enriched/case_summaries.jsonl --conflicts data/output/conflicts/case_conflict_assessments.jsonl --output data/output/retrieval
python scripts/validate_official_pipeline.py --official-kb data/output/official_kb/official_kb.jsonl --cases data/output/enriched/case_summaries.jsonl --assessments data/output/conflicts/case_conflict_assessments.jsonl --corpus data/output/retrieval/retrieval_corpus.jsonl
```

The current pipeline validator requires `review_after >= retrieved_at`; deliberately expired, unverified PDF chunks will not pass it. Resolve source verification before using those records as a validated snapshot. Do not alter dates merely to satisfy a check.

After successful validation, select your corpus explicitly:

```bash
python -m support_agent.web --provider local --corpus data/output/retrieval/retrieval_corpus.jsonl
```

Review it periodically with `scripts/review_knowledge.py`, as in step 3 but using your private corpus path and the relevant date. A lack of rule-detected conflicts does not prove the advice is current. Historical private processing figures are documented in [data scope](data_scope.md); they are not the size of the public demo.

## Response fields

| Field | Meaning |
| --- | --- |
| `answer` | Response text. |
| `route` | `answer`, `clarify`, or `escalate`. |
| `reason` | Policy reason for the decision. |
| `citations` | Material provided to generation, or the record rendered by the local provider. |
| `session_id` | Conversation identifier. |
| `provider` | Selected provider. |

Human escalation only produces a prompt and routing decision. A channel adapter is needed to create real tickets. Software tests cannot establish customer satisfaction, saved labor, real resolution rates or model costs.
