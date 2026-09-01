#!/usr/bin/env python3
"""Validate official coverage, conflict decisions, corpus policy, and redaction."""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any


SECRET_RE = re.compile(
    r"\b(?:nb|sk|rk|pk|key)[_-][A-Za-z0-9_-]{16,}\b|"
    r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}",
    re.I,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-kb", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--assessments", required=True)
    parser.add_argument("--corpus", required=True)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    args = parse_args()
    official = read_jsonl(Path(args.official_kb))
    cases = read_jsonl(Path(args.cases))
    assessments = read_jsonl(Path(args.assessments))
    corpus = read_jsonl(Path(args.corpus))

    official_ids = {str(row["doc_id"]) for row in official}
    case_ids = {str(row["ticket_id"]) for row in cases}
    assessment_ids = {str(row["ticket_id"]) for row in assessments}
    assert len(official_ids) == len(official), "Duplicate official document ID"
    assert len(case_ids) == len(cases), "Duplicate case ID"
    assert case_ids == assessment_ids, "Conflict assessments do not cover all cases"

    for row in official:
        assert date.fromisoformat(row["review_after"]) >= date.fromisoformat(row["retrieved_at"])
        assert row["source_url"], f"Missing source for {row['doc_id']}"

    blocked = {
        str(row["ticket_id"])
        for row in assessments
        if row["retrieval_policy"] == "blocked_pending_review"
    }
    corpus_case_ids = {
        str(row["ticket_id"])
        for row in corpus
        if row["document_type"] == "historical_case_summary"
    }
    corpus_official_ids = {
        row["document_id"].removeprefix("official:")
        for row in corpus
        if row["document_type"] == "official_knowledge"
    }
    assert not blocked.intersection(corpus_case_ids), "Blocked case entered retrieval corpus"
    assert corpus_case_ids == case_ids - blocked, "Retrieval case selection mismatch"
    expected_official_ids = {
        str(row["doc_id"])
        for row in official
        if row.get("retrieval_policy", "include") != "excluded"
    }
    excluded_official_ids = official_ids - expected_official_ids
    assert corpus_official_ids == expected_official_ids, "Official retrieval policy mismatch"
    assert not corpus_official_ids.intersection(excluded_official_ids)

    serialized = "\n".join(json.dumps(row, ensure_ascii=False) for row in corpus)
    secret_matches = SECRET_RE.findall(serialized)
    assert not secret_matches, f"Possible unredacted secrets found: {len(secret_matches)}"

    print(
        json.dumps(
            {
                "status": "ok",
                "official_documents": len(official),
                "excluded_official_documents": len(excluded_official_ids),
                "case_assessments": len(assessments),
                "blocked_cases_absent": len(blocked),
                "retrieval_documents": len(corpus),
                "secret_scan": "clean",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
