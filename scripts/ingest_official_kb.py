#!/usr/bin/env python3
"""Validate and normalize official knowledge JSONL files into one KB snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


REQUIRED = {
    "doc_id",
    "title",
    "content",
    "authority",
    "source_url",
    "retrieved_at",
    "review_after",
    "volatility",
    "categories",
    "keywords",
    "claims",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Directory containing official *.jsonl files")
    parser.add_argument("--output", required=True, help="Output directory")
    return parser.parse_args()


def validate(row: dict[str, Any], source_file: Path, line_no: int) -> dict[str, Any]:
    missing = REQUIRED - row.keys()
    if missing:
        raise SystemExit(f"{source_file}:{line_no}: missing fields {sorted(missing)}")
    if row["authority"] not in {"official_public_website", "official_internal_document"}:
        raise SystemExit(f"{source_file}:{line_no}: invalid authority")
    if row["volatility"] not in {"low", "medium", "high"}:
        raise SystemExit(f"{source_file}:{line_no}: invalid volatility")
    if not str(row["source_url"]).startswith(("https://", "internal://")):
        raise SystemExit(f"{source_file}:{line_no}: source_url must be https:// or internal://")
    for field in ("retrieved_at", "review_after"):
        try:
            date.fromisoformat(str(row[field]))
        except ValueError as exc:
            raise SystemExit(f"{source_file}:{line_no}: invalid {field}") from exc
    for field in ("categories", "keywords", "claims"):
        if not isinstance(row[field], list):
            raise SystemExit(f"{source_file}:{line_no}: {field} must be a list")
    normalized = dict(row)
    normalized.setdefault("products", [])
    normalized.setdefault("clients", [])
    normalized.setdefault("audience", "customer_safe")
    normalized.setdefault("retrieval_policy", "include")
    normalized["content_hash"] = hashlib.sha256(
        str(row["content"]).encode("utf-8")
    ).hexdigest()
    normalized["source_file"] = source_file.name
    return normalized


def main() -> None:
    args = parse_args()
    input_dir = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    files = sorted(input_dir.rglob("*.jsonl"))
    if not files:
        raise SystemExit(f"No official JSONL files found in {input_dir}")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in files:
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                row = validate(json.loads(line), path, line_no)
                doc_id = str(row["doc_id"])
                if doc_id in seen:
                    raise SystemExit(f"Duplicate doc_id: {doc_id}")
                seen.add(doc_id)
                rows.append(row)

    rows.sort(key=lambda row: str(row["doc_id"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "official_kb.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = {
        "document_count": len(rows),
        "authorities": dict(Counter(row["authority"] for row in rows)),
        "volatility": dict(Counter(row["volatility"] for row in rows)),
        "categories": dict(Counter(category for row in rows for category in row["categories"])),
        "sources": sorted({row["source_url"] for row in rows}),
        "audiences": dict(Counter(row["audience"] for row in rows)),
        "retrieval_policies": dict(Counter(row["retrieval_policy"] for row in rows)),
        "note": "Official snapshots are source-attributed and time-bounded; review_after must be enforced before production use.",
    }
    (output_dir / "official_kb_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
