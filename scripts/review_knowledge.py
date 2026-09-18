#!/usr/bin/env python3
"""Inventory expired knowledge without automatically renewing source claims."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path


def build_review(rows, as_of):
    queue = []
    counts = Counter()
    for row in rows:
        if row.get("precedence") != "P1":
            if row.get("precedence") == "P2":
                counts["historical_total"] += 1
                if row.get("conflict_status") == "no_rule_conflict_detected" and row.get("audience") not in {"agent_internal", "restricted_internal"}:
                    counts["historical_eligible_before_query_filter"] += 1
            continue
        counts["official_total"] += 1
        audience = row.get("audience", "customer_safe")
        counts[f"audience_{audience}"] += 1
        try:
            deadline = date.fromisoformat(str(row.get("review_after", "")))
            status = "expired" if deadline < as_of else "within_review_window"
        except ValueError:
            status = "missing_or_invalid_review_date"
        counts[status] += 1
        if audience == "customer_safe" and status == "within_review_window":
            counts["customer_official_eligible_before_query_filter"] += 1
        if status != "within_review_window":
            queue.append({
                "document_id": row.get("document_id", row.get("doc_id")),
                "title": row.get("title"), "source_url": row.get("source_url"),
                "audience": audience, "review_after": row.get("review_after"),
                "status": status, "review_state": "pending_source_verification",
                "content_sha256": hashlib.sha256(str(row.get("text", row.get("content", ""))).encode()).hexdigest(),
                "reviewer": None, "verified_at": None, "verification_evidence": None,
                "next_action": "Reopen the current authoritative source; record evidence and reviewer before changing review_after. An old PDF alone cannot confirm current policy.",
            })
    summary = {"as_of": as_of.isoformat(), "counts": dict(sorted(counts.items())),
               "pending_review": len(queue),
               "note": "Metadata review only. No claims were renewed. Eligibility excludes query-specific relevance and error-code checks."}
    return summary, queue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output", type=Path, default=Path("runtime/knowledge_review"))
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.corpus.read_text(encoding="utf-8").splitlines() if line.strip()]
    summary, queue = build_review(rows, args.as_of)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "review_queue.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in queue), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
