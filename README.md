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
