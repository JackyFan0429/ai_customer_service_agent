#!/usr/bin/env python3
"""Validate output counts, ticket identities, tiers, and evidence references."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="canonical_cases.jsonl")
    parser.add_argument("--output", required=True, help="Enrichment output directory")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parsed = args()
    source = read_jsonl(Path(parsed.source))
    output = Path(parsed.output)
    enriched = read_jsonl(output / "canonical_cases_enriched.jsonl")
    summaries = read_jsonl(output / "case_summaries.jsonl")
    low = read_jsonl(output / "low_confidence_cases.jsonl")
    review = read_jsonl(output / "conflicts_or_review.jsonl")

    source_ids = [str(row["ticket_id"]) for row in source]
    enriched_ids = [str(row["ticket_id"]) for row in enriched]
    assert len(source) == len(enriched), "Source/enriched count mismatch"
    assert source_ids == enriched_ids, "Ticket ordering or identity changed"
    assert len(source_ids) == len(set(source_ids)), "Source ticket IDs are not unique"

    summary_ids = {str(row["ticket_id"]) for row in summaries}
    low_ids = {str(row["ticket_id"]) for row in low}
    review_ids = {str(row["ticket_id"]) for row in review}

    expected_summary = {
        str(row["ticket_id"])
        for row in enriched
        if row["enrichment"]["quality"]["retrieval_status"] == "eligible"
    }
    expected_low = {
        str(row["ticket_id"])
        for row in enriched
        if row["enrichment"]["quality"]["semantic_tier"] == "archive_only"
    }
    expected_review = {
        str(row["ticket_id"])
        for row in enriched
        if row["enrichment"]["quality"]["requires_human_review"]
    }
    assert summary_ids == expected_summary, "Summary selection mismatch"
    assert low_ids == expected_low, "Low-confidence selection mismatch"
    assert review_ids == expected_review, "Review selection mismatch"

    evidence_checks = 0
    for row in enriched:
        message_ids = {
            message.get("telegram_message_id")
            for message in row.get("messages", [])
            if message.get("telegram_message_id") is not None
        }
        evidence = row["enrichment"]["evidence"]
        for key, values in evidence.items():
            missing = {value for value in values if value is not None} - message_ids
            assert not missing, f"Ticket {row['ticket_id']} has missing {key}: {missing}"
            evidence_checks += len(values)

    print(
        json.dumps(
            {
                "status": "ok",
                "source_cases": len(source),
                "enriched_cases": len(enriched),
                "eligible_summaries": len(summaries),
                "archive_only": len(low),
                "review_queue": len(review),
                "evidence_references_checked": evidence_checks,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

