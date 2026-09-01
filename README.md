# Krill AI Customer Support

An evidence-grounded customer support agent built on an official knowledge base and historical support cases. The project currently includes knowledge processing, official knowledge conflict checks, hybrid retrieval, and a runnable customer support response workflow.

## Current Capabilities

* P1 official knowledge takes priority; P2 historical cases are used only as troubleshooting references.
* Automatically excludes outdated official materials, potentially conflicting cases, and restricted content.
* Routes questions to direct answers, requests for additional information, or human escalation.
* Internal knowledge may influence routing, but it is never included in customer-facing prompts or citation lists.
* Supports both a fully local deterministic mode and an OpenAI Responses API mode.
* Returns structured evidence for easier auditing and future integration with Telegram or web services.

## Quick Start

Requires Python 3.11 or later. The default local mode requires no third-party dependencies or API key.

```bash
python3 -m krill_agent.cli "How should I configure the Codex Base URL?"
```

Interactive mode:

```bash
python3 -m krill_agent.cli
```

JSON output:

```bash
python3 -m krill_agent.cli --json "How should I configure the Codex Base URL?"
```

## Using OpenAI Models

The project calls models through the Responses API. The model is not hard-coded and must be explicitly specified in the deployment environment.

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="your-model-id"
python3 -m krill_agent.cli --provider openai "How should I configure the Codex Base URL?"
```

Optional environment variables:

| Variable               | Purpose                      | Default                                        |
| ---------------------- | ---------------------------- | ---------------------------------------------- |
| `KRILL_AGENT_PROVIDER` | `local` or `openai`          | `local`                                        |
| `KRILL_AGENT_CORPUS`   | Retrieval corpus path        | `data/output/retrieval/retrieval_corpus.jsonl` |
| `OPENAI_API_KEY`       | OpenAI API key               | None                                           |
| `OPENAI_MODEL`         | Explicitly selected model ID | None                                           |
| `OPENAI_BASE_URL`      | Responses API base URL       | `https://api.openai.com/v1`                    |

Do not commit `.env` files, API keys, customer data, or internal PDFs to Git.

## Running Tests

The core agent tests do not depend on external services:

```bash
python3 -m unittest tests.test_agent tests.test_providers -v
```

The full test suite also validates PDF strikethrough extraction logic and requires the project's PDF runtime dependencies:

```bash
python3 -m unittest discover -s tests -v
```

## Knowledge Base Pipeline

Raw customer data and generated outputs are excluded from Git by default. To rebuild the full pipeline, run the following steps in order:

```bash
python3 scripts/enrich_cases.py \
  --input data/input/case_kb_preview/canonical_cases.jsonl \
  --output data/output/enriched

python3 scripts/extract_pdf_official_kb.py \
  --input knowledge/official/sources/krillai_ticket_knowledge_base.pdf \
  --output knowledge/official/internal/krill_internal_pdf.jsonl \
  --audit knowledge/official/audit/krill_internal_pdf_audit.json \
  --report knowledge/official/audit/krill_internal_pdf_report.json

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
```

## Documentation

* [System Architecture](docs/architecture.md)
* [Operations and Deployment](docs/operations.md)
* [Safety and Response Policy](docs/safety.md)
* [Official Knowledge Base Policy](docs/official_kb_policy.md)
* [Historical Case Enrichment Schema](docs/enrichment_schema.md)

## Project Status

The current version includes a runnable agent core and CLI. Before production integration, the project still needs persistent sessions, Telegram/web channel adapters, real-time account tools, a human ticketing system, and an online evaluation set.
