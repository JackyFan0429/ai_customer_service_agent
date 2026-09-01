#!/usr/bin/env python3
"""Compare historical case candidates with source-attributed official claims."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


CURRENT_FACT_RE = re.compile(
    r"(?:现在|目前|当前|最新|已经下线|已下线|不再支持|价格|售价|倍率|额度|套餐|退款规则|"
    r"暂时|下架|上线|有货|售罄|恢复|支持中|支持.{0,12}模型|模型.{0,12}(?:可用|不可用|下线))",
    re.I,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="case_summaries.jsonl")
    parser.add_argument("--official-kb", required=True, help="official_kb.jsonl")
    parser.add_argument("--output", required=True, help="Output directory")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def case_text(case: dict[str, Any]) -> str:
    parts = [case.get("problem_summary", ""), *case.get("error_signatures", [])]
    parts.extend(x.get("text", "") for x in case.get("historical_solution_candidates", []))
    return "\n".join(str(x) for x in parts if x)


def solution_text(case: dict[str, Any]) -> str:
    return "\n".join(
        str(x.get("text", "")) for x in case.get("historical_solution_candidates", [])
    )


def relevant(case: dict[str, Any], doc: dict[str, Any], text: str) -> bool:
    case_categories = {case.get("primary_category"), *case.get("category_tags", [])}
    if case_categories.intersection(doc.get("categories", [])):
        return True
    if set(case.get("products", [])).intersection(doc.get("products", [])):
        return True
    haystack = text.casefold()
    return any(str(keyword).casefold() in haystack for keyword in doc.get("keywords", []))


def assess(case: dict[str, Any], official_docs: list[dict[str, Any]]) -> dict[str, Any]:
    text = case_text(case)
    historical_answer = solution_text(case)
    related = [doc for doc in official_docs if relevant(case, doc, text)]
    conflicts: list[dict[str, Any]] = []
    for doc in related:
        for claim in doc.get("claims", []):
            for pattern in claim.get("contradiction_patterns", []):
                match = re.search(pattern, historical_answer, re.I | re.S)
                if match:
                    conflicts.append(
                        {
                            "official_doc_id": doc["doc_id"],
                            "claim_id": claim.get("claim_id"),
                            "official_statement": claim.get("statement"),
                            "historical_excerpt": match.group(0)[:240],
                            "source_url": doc["source_url"],
                        }
                    )

    volatile_related = [doc for doc in related if doc.get("volatility") == "high"]
    current_fact_risk = bool(volatile_related and CURRENT_FACT_RE.search(historical_answer))
    if conflicts:
        status = "potential_conflict"
        retrieval_policy = "blocked_pending_review"
        reasons = ["historical_answer_may_contradict_official_claim"]
    elif current_fact_risk:
        status = "potentially_outdated_current_fact"
        retrieval_policy = "historical_evidence_only"
        reasons = ["historical_answer_contains_time_sensitive_claim"]
    elif related:
        status = "no_rule_conflict_detected"
        retrieval_policy = "historical_evidence_only"
        reasons = []
    else:
        status = "insufficient_official_coverage"
        retrieval_policy = "historical_evidence_only"
        reasons = ["no_related_official_document"]

    return {
        "ticket_id": case["ticket_id"],
        "status": status,
        "retrieval_policy": retrieval_policy,
        "review_required": bool(conflicts or current_fact_risk),
        "review_reasons": reasons,
        "related_official_doc_ids": [doc["doc_id"] for doc in related],
        "related_official_sources": sorted({doc["source_url"] for doc in related}),
        "potential_conflicts": conflicts,
        "limitations": [
            "Rule-based check only; no semantic entailment model was used.",
            "No conflict detected does not prove that a historical answer is correct.",
        ],
    }


def main() -> None:
    args = parse_args()
    cases = read_jsonl(Path(args.cases))
    official_all = read_jsonl(Path(args.official_kb))
    official = [row for row in official_all if row.get("retrieval_policy", "include") != "excluded"]
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    assessments = [assess(case, official) for case in cases]
    conflicts = [row for row in assessments if row["review_required"]]
    with (output_dir / "case_conflict_assessments.jsonl").open("w", encoding="utf-8") as handle:
        for row in assessments:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (output_dir / "potential_conflicts.jsonl").open("w", encoding="utf-8") as handle:
        for row in conflicts:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = {
        "case_count": len(cases),
        "official_document_count": len(official),
        "excluded_official_document_count": len(official_all) - len(official),
        "statuses": dict(Counter(row["status"] for row in assessments)),
        "blocked_pending_review": sum(row["retrieval_policy"] == "blocked_pending_review" for row in assessments),
        "review_required": len(conflicts),
        "warning": "Historical cases remain evidence only even when no rule conflict is detected.",
    }
    (output_dir / "conflict_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
