#!/usr/bin/env python3
"""Validate frozen retrieval labels and split integrity; never run retrieval."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from support_agent.desk.tools import TOOL_DESCRIPTIONS

DEFAULT_DATASET = ROOT / "evals/retrieval/lumen-v1"
SPLITS = ("development", "holdout")
KINDS = ("kb_answerable", "kb_and_business_data", "no_kb_answer", "business_data_only")
ANSWERABLE = set(KINDS[:2])


def normalized_query(value):
    """Catch identical questions despite spacing, case and punctuation changes."""
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def validate_records(knowledge, cases, groups, *, require_reviewed=False):
    errors = []
    by_id = {row["id"]: row for row in knowledge}
    if len(by_id) != len(knowledge):
        errors.append("knowledge: duplicate IDs")
    seen_ids, seen_queries, group_splits, used_groups = set(), {}, {}, set()
    kind_counts, review_counts, coverage = Counter(), Counter(), Counter()
    per_split = {s: {"questions": 0, "groups": set(), "answerability": Counter(), "knowledge": Counter()} for s in SPLITS}

    for case in cases:
        if not isinstance(case, dict):
            errors.append("case: expected an object")
            continue
        cid = case.get("id", "<missing id>")
        def fail(message):
            errors.append(f"{cid}: {message}")

        if not isinstance(cid, str) or not cid.strip() or cid == "<missing id>":
            fail("missing or invalid ID")
            continue
        if cid in seen_ids:
            fail("duplicate ID")
        seen_ids.add(cid)
        split, group, kind = case.get("split"), case.get("group_id"), case.get("answerability")
        if split not in SPLITS:
            fail("invalid split")
            continue
        if not isinstance(group, str) or group not in groups:
            fail("unknown problem group")
            continue
        used_groups.add(group)
        declared = groups[group]
        if declared.get("split") != split:
            fail("split differs from frozen group allocation")
        if not isinstance(declared.get("intent"), str) or not declared["intent"].strip():
            fail("group needs a business-subproblem description")
        if group in group_splits and group_splits[group] != split:
            fail("problem group crosses development and holdout")
        group_splits[group] = split
        if kind not in KINDS:
            fail("invalid answerability")
            continue
        kind_counts[kind] += 1
        bucket = per_split[split]
        bucket["questions"] += 1
        bucket["groups"].add(group)
        bucket["answerability"][kind] += 1

        query = case.get("query")
        if not isinstance(query, str) or not normalized_query(query):
            fail("query must contain text")
        else:
            if len(query) > 2000:
                fail("query exceeds the portal's 2000-character search input")
            key = normalized_query(query)
            if key in seen_queries:
                fail(f"duplicate normalized query: {seen_queries[key]}")
            seen_queries[key] = cid
        if not isinstance(case.get("rationale"), str) or not case["rationale"].strip():
            fail("label needs a rationale")
        tags = case.get("tags")
        if not isinstance(tags, list) or not tags or not all(isinstance(t, str) and t.strip() for t in tags):
            fail("tags must be nonempty strings")

        relevant = case.get("relevant_ids")
        if not isinstance(relevant, list) or not all(isinstance(k, str) for k in relevant):
            fail("relevant_ids must be a list of knowledge IDs")
            continue
        if len(set(relevant)) != len(relevant):
            fail("duplicate relevant knowledge ID")
        if set(relevant) - by_id.keys():
            fail("unknown relevant knowledge ID")
        if (kind in ANSWERABLE) != bool(relevant):
            fail("relevant_ids do not match answerability")
        coverage.update(relevant)
        bucket["knowledge"].update(relevant)

        evidence = case.get("evidence")
        if not isinstance(evidence, list) or not all(isinstance(e, dict) for e in evidence):
            fail("evidence must be a list of objects")
            continue
        evidence_ids = [e.get("knowledge_id") for e in evidence]
        if sorted(str(k) for k in evidence_ids) != sorted(relevant):
            fail("evidence must cover each relevant ID exactly once")
        for item in evidence:
            kid, quote = item.get("knowledge_id"), item.get("quote")
            doc = by_id.get(kid) if isinstance(kid, str) else None
            if doc is None or not isinstance(quote, str) or not quote.strip() or quote not in doc["content"]:
                fail("evidence quote is missing or not in the frozen knowledge text")

        tools = case.get("required_tools")
        if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
            fail("required_tools must be a list")
        else:
            if len(set(tools)) != len(tools) or set(tools) - (TOOL_DESCRIPTIONS.keys() - {"search_kb"}):
                fail("invalid business read tool")
            if (kind in {"kb_and_business_data", "business_data_only"}) != bool(tools):
                fail("business-data requirement does not match answerability")

        distractors = case.get("non_relevant_examples")
        if not isinstance(distractors, list) or not all(isinstance(d, dict) for d in distractors):
            fail("non_relevant_examples must be a list of objects")
        else:
            for item in distractors:
                kid = item.get("knowledge_id")
                if not isinstance(kid, str) or kid not in by_id or kid in relevant:
                    fail("non-relevant example has an unknown or relevant ID")
                if not isinstance(item.get("reason"), str) or not item["reason"].strip():
                    fail("non-relevant example needs a reason")

        review = case.get("review")
        if not isinstance(review, dict):
            fail("missing review record")
            continue
        status = review.get("status")
        if status not in {"pending_owner_review", "approved", "needs_revision"}:
            fail("invalid review status")
            continue
        review_counts[status] += 1
        if status == "approved":
            if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
                fail("approved label needs a named human reviewer")
            try:
                date.fromisoformat(review.get("reviewed_at", ""))
            except (TypeError, ValueError):
                fail("approved label needs reviewed_at in YYYY-MM-DD format")
        elif status == "needs_revision":
            fail("label has unresolved review changes")
        elif require_reviewed:
            fail("label is pending owner review")

    if used_groups != set(groups):
        errors.append("groups: allocation includes groups with no valid questions")
    return {
        "valid": not errors, "errors": errors, "questions": len(cases), "groups": len(used_groups),
        "answerability": {kind: kind_counts[kind] for kind in KINDS},
        "review_status": dict(review_counts),
        "knowledge_coverage": {kid: coverage[kid] for kid in sorted(by_id)},
        "splits": {s: {"questions": v["questions"], "groups": len(v["groups"]),
                        "answerability": {k: v["answerability"][k] for k in KINDS},
                        "knowledge_coverage": {k: v["knowledge"][k] for k in sorted(by_id)}} for s, v in per_split.items()},
        "metric_population_sizes": {"recall_at_4_and_mrr_at_4": sum(kind_counts[k] for k in ANSWERABLE),
                                    "no_answer_false_retrieval_rate": kind_counts["no_kb_answer"],
                                    "dynamic_diagnostic_only": kind_counts["business_data_only"]},
        "retrieval_executed": False, "external_model_calls": 0,
        "limitation": "Structural and exact-evidence checks only. Semantic relevance and paraphrase grouping still need human review; no retrieval score was measured.",
    }


def validate_dataset(directory=DEFAULT_DATASET, *, require_reviewed=False):
    directory = Path(directory)
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        knowledge = json.loads((directory / "knowledge.json").read_text(encoding="utf-8"))
        cases, file_errors = [], []
        for split in SPLITS:
            rows = [json.loads(line) for line in (directory / f"{split}.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            if len(rows) != manifest["splits"][split]["expected_count"]:
                file_errors.append(f"{split}: question count differs from manifest")
            if any(not isinstance(c, dict) or c.get("split") != split for c in rows):
                file_errors.append(f"{split}: wrong split inside file")
            cases.extend(rows)
        report = validate_records(knowledge, cases, manifest["split_policy"]["groups"], require_reviewed=require_reviewed)
        if manifest["schema_version"] != 1 or len(knowledge) != manifest["knowledge_record_count"]:
            file_errors.append("manifest: schema version or knowledge count mismatch")
        instant = datetime.fromisoformat(manifest["as_of"])
        state = manifest["knowledge_state"]
        if instant.utcoffset() is None or state["published"] != 1 or date.fromisoformat(state["review_after"]) < instant.astimezone(timezone.utc).date():
            file_errors.append("knowledge: snapshot must be published and valid at the fixed instant")
        for name in ("knowledge.json", "development.jsonl", "holdout.jsonl"):
            actual = hashlib.sha256((directory / name).read_bytes()).hexdigest()
            if actual != manifest["files_sha256"][name]:
                file_errors.append(f"{name}: SHA-256 differs from the frozen manifest; revisions need a new dataset version")
        report["errors"].extend(file_errors)
        report["valid"] = not report["errors"]
        report["dataset_id"] = manifest["dataset_id"]
        report["require_reviewed"] = require_reviewed
        report["files_sha256"] = manifest["files_sha256"]
        return report
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        return {"valid": False, "errors": [f"Dataset could not be read or has an invalid structure: {type(error).__name__}"],
                "retrieval_executed": False, "external_model_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=Path("runtime/retrieval_dataset_validation.json"))
    parser.add_argument("--require-reviewed", action="store_true", help="Fail until every label has a recorded human review")
    args = parser.parse_args()
    report = validate_dataset(args.dataset, require_reviewed=args.require_reviewed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
