# AI customer agent knowledge pipeline

This repository currently implements the first semantic-enrichment stage for a
historical Telegram support-case knowledge base.

## Run

```bash
python3 scripts/enrich_cases.py \
  --input data/input/case_kb_preview/canonical_cases.jsonl \
  --output data/output/enriched
```

No external API or third-party Python dependency is required for this baseline.

Validate a completed run with:

```bash
python3 scripts/validate_enrichment.py \
  --source data/input/case_kb_preview/canonical_cases.jsonl \
  --output data/output/enriched
```

## Outputs

- `canonical_cases_enriched.jsonl`: all canonical records plus enrichment.
- `case_summaries.jsonl`: only records currently eligible for retrieval.
- `low_confidence_cases.jsonl`: archive-only records.
- `conflicts_or_review.jsonl`: human-review queue. Conflict status remains
  unchecked until an official knowledge base is connected.
- `enrichment_report.json`: counts, categories, quality flags, and limitations.

The input and generated output directories are ignored by Git because support
data can contain sensitive content.

## Official knowledge and conflict checks

Official snapshots live in `knowledge/official/*.jsonl`. Every record must include
a source URL, retrieval date, review deadline, volatility level, categories,
keywords, and explicit claims. Public snapshots are never generated from historical
support answers.

The internal official PDF is preserved locally as
`knowledge/official/sources/krillai_ticket_knowledge_base.pdf`. It is ignored by
Git. Extract it with the bundled Python runtime and `pdfplumber`:

```bash
python3 scripts/extract_pdf_official_kb.py \
  --input knowledge/official/sources/krillai_ticket_knowledge_base.pdf \
  --output knowledge/official/internal/krill_internal_pdf.jsonl \
  --audit knowledge/official/audit/krill_internal_pdf_audit.json \
  --report knowledge/official/audit/krill_internal_pdf_report.json
```

Visual strike-through lines are excluded before section chunking and retained only
in the audit file. Restricted payment addresses, exact internal platform limits,
and internal pricing sections are marked `retrieval_policy=excluded`. Other
internal operational guidance is tagged `agent_internal` with a non-disclosure
generation policy.

```bash
python3 scripts/ingest_official_kb.py \
  --input knowledge/official \
  --output data/output/official_kb

python3 scripts/check_case_conflicts.py \
  --cases data/output/enriched/case_summaries.jsonl \
  --official-kb data/output/official_kb/official_kb.jsonl \
  --output data/output/conflicts

python3 scripts/build_retrieval_corpus.py \
  --official-kb data/output/official_kb/official_kb.jsonl \
  --cases data/output/enriched/case_summaries.jsonl \
  --conflicts data/output/conflicts/case_conflict_assessments.jsonl \
  --output data/output/retrieval

python3 scripts/hybrid_search.py \
  --corpus data/output/retrieval/retrieval_corpus.jsonl \
  --query "Codex 配置 Base URL 后连接失败"
```

Validate policy enforcement and the secondary secret scan with:

```bash
python3 scripts/validate_official_pipeline.py \
  --official-kb data/output/official_kb/official_kb.jsonl \
  --cases data/output/enriched/case_summaries.jsonl \
  --assessments data/output/conflicts/case_conflict_assessments.jsonl \
  --corpus data/output/retrieval/retrieval_corpus.jsonl
```

The baseline combines BM25 with character n-gram similarity so Chinese and exact
error strings both work without an embedding service. Official P1 records receive
a small authority boost only when they are already relevant. Historical P2 records
remain troubleshooting evidence and cannot establish current facts.
