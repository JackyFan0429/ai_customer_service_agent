#!/usr/bin/env python3
"""Build an authority-aware corpus from official documents and historical cases."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-kb", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--conflicts", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    args = parse_args()
    official = read_jsonl(Path(args.official_kb))
    cases = read_jsonl(Path(args.cases))
    conflict_rows = read_jsonl(Path(args.conflicts))
    conflict_map = {str(row["ticket_id"]): row for row in conflict_rows}
    corpus: list[dict[str, Any]] = []

    excluded_official = 0
    for doc in official:
        if doc.get("retrieval_policy", "include") == "excluded":
            excluded_official += 1
            continue
        audience = doc.get("audience", "customer_safe")
        corpus.append(
            {
                "document_id": f"official:{doc['doc_id']}",
                "document_type": "official_knowledge",
                "authority": doc["authority"],
                "precedence": "P1",
                "title": doc["title"],
                "text": doc["content"],
                "products": doc.get("products", []),
                "clients": doc.get("clients", []),
                "categories": doc.get("categories", []),
                "keywords": doc.get("keywords", []),
                "source_url": doc["source_url"],
                "retrieved_at": doc["retrieved_at"],
                "review_after": doc["review_after"],
                "volatility": doc["volatility"],
                "audience": audience,
                "conflict_status": "authoritative_source",
                "generation_policy": (
                    "may_inform_internal_routing_not_disclose_verbatim"
                    if audience == "agent_internal"
                    else "may_support_current_facts_until_review_after"
                ),
            }
        )

    blocked = 0
    for case in cases:
        ticket_id = str(case["ticket_id"])
        assessment = conflict_map[ticket_id]
        if assessment["retrieval_policy"] == "blocked_pending_review":
            blocked += 1
            continue
        corpus.append(
            {
                "document_id": f"case:{ticket_id}",
                "document_type": "historical_case_summary",
                "authority": "historical_case",
                "precedence": "P2",
                "title": case.get("problem_summary") or f"Historical case {ticket_id}",
                "text": case.get("case_summary", ""),
                "products": case.get("products", []),
                "clients": case.get("clients", []),
                "categories": list(dict.fromkeys([case.get("primary_category"), *case.get("category_tags", [])])),
                "keywords": [*case.get("error_signatures", []), *case.get("products", [])],
                "ticket_id": ticket_id,
                "semantic_tier": case["quality"]["semantic_tier"],
                "conflict_status": assessment["status"],
                "related_official_doc_ids": assessment["related_official_doc_ids"],
                "evidence": case.get("evidence", {}),
                "generation_policy": "historical_troubleshooting_evidence_only",
            }
        )

    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "retrieval_corpus.jsonl").open("w", encoding="utf-8") as handle:
        for row in corpus:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {
        "document_count": len(corpus),
        "document_types": dict(Counter(row["document_type"] for row in corpus)),
        "precedence": dict(Counter(row["precedence"] for row in corpus)),
        "blocked_historical_cases": blocked,
        "excluded_official_documents": excluded_official,
        "precedence_rule": "P1 official knowledge outranks P2 historical evidence when both are relevant.",
    }
    (output_dir / "retrieval_corpus_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
