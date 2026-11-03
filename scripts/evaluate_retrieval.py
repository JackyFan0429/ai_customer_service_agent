#!/usr/bin/env python3
"""Compare retrieval on development, freeze settings, then evaluate holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.validate_retrieval_dataset import ANSWERABLE, DEFAULT_DATASET, validate_records
from support_agent.retrieval import search

METHODS = ("bm25", "char_ngram", "hybrid")
CONFIG = {
    "top_k": 4, "minimum_query_term_coverage": 0.12, "query_character_limit": 2000,
    "bm25": {"k1": 1.5, "b": 0.75, "normalization": "per-query maximum"},
    "character_ngram_sizes": [2, 3],
    "method_weights": {"bm25": [1.0, 0.0], "char_ngram": [0.0, 1.0], "hybrid": [0.62, 0.38]},
    "common_business_rules": {"p1_metadata_boost_max": 0.22, "boost_base_threshold": 0.03,
                              "p1_priority_score_threshold": 0.32, "ties": "stable corpus order",
                              "filter_order": "published/current corpus -> rank -> top 4 -> coverage >= 0.12; no refill"},
    "query_rewriting": False,
    "development_selection_order": ["no retrieval exceptions", "higher macro recall@4",
                                    "lower no-answer false retrieval", "higher MRR@4", "keep hybrid on a tie"],
}
IMPLEMENTATION_FILES = ("support_agent/retrieval.py", "support_agent/desk/tools.py",
                        "scripts/validate_retrieval_dataset.py", "scripts/evaluate_retrieval.py")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def identity(directory):
    """Only read the manifest here, never holdout query text or labels."""
    manifest = read_json(directory / "manifest.json")
    return {"dataset_id": manifest["dataset_id"], "dataset_manifest_sha256": digest(directory / "manifest.json"),
            "dataset_files_sha256": manifest["files_sha256"], "as_of": manifest["as_of"],
            "configuration": CONFIG,
            "implementation_sha256": {name: digest(ROOT / name) for name in IMPLEMENTATION_FILES}}


def load_split(directory, split):
    if split not in {"development", "holdout"}:
        raise ValueError("Choose development or holdout")
    manifest = read_json(directory / "manifest.json")
    for name in ("knowledge.json", f"{split}.jsonl"):
        if digest(directory / name) != manifest["files_sha256"][name]:
            raise ValueError(f"Frozen dataset changed: {name}")
    knowledge = read_json(directory / "knowledge.json")
    cases = [json.loads(line) for line in (directory / f"{split}.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    groups = {key: value for key, value in manifest["split_policy"]["groups"].items() if value["split"] == split}
    checked = validate_records(knowledge, cases, groups)
    if not checked["valid"]:
        raise ValueError("Invalid selected-split labels: " + "; ".join(checked["errors"]))
    if len(cases) != manifest["splits"][split]["expected_count"] or any(c["split"] != split for c in cases):
        raise ValueError("Selected split does not match its manifest")
    state = manifest["knowledge_state"]
    instant = datetime.fromisoformat(manifest["as_of"])
    if instant.utcoffset() is None:
        raise ValueError("Fixed business time needs a UTC offset")
    available = state["published"] == 1 and date.fromisoformat(state["review_after"]) >= instant.astimezone(timezone.utc).date()
    corpus = [{"document_id": k["id"], "title": k["title"], "text": k["content"],
               "categories": [k["category"]], "keywords": k["keywords"], "precedence": "P1"}
              for k in knowledge] if available else []
    return manifest, corpus, cases


def score_case(case, ranked, *, error=None):
    """Grade only labels; the ranker receives query text, never gold evidence."""
    raw = ranked[:CONFIG["top_k"]]
    final = [r for r in raw if r["query_term_coverage"] >= CONFIG["minimum_query_term_coverage"]]
    if error:
        final = []
    ids = [r["document_id"] for r in final]
    gold = set(case["relevant_ids"])
    answerable = case["answerability"] in ANSWERABLE
    first = next((i for i, key in enumerate(ids, 1) if key in gold), None)
    missed = sorted(gold - set(ids))
    raw_ids = {r["document_id"] for r in raw}
    first_raw = next((i for i, row in enumerate(raw, 1) if row["document_id"] in gold), None)
    ranked_ids = {r["document_id"] for r in ranked}
    known_misses = {key: "retrieval_exception" if error else "coverage_filter" if key in raw_ids else "outside_top_k" if key in ranked_ids else "not_ranked"
                    for key in missed}
    fields = ("document_id", "title", "score", "lexical_score", "semantic_ngram_score", "authority_boost", "query_term_coverage")
    return {"id": case["id"], "group_id": case["group_id"], "query": case["query"],
            "tags": case["tags"], "answerability": case["answerability"], "relevant_ids": case["relevant_ids"],
            "ranked_candidates": [{"rank": i, **{k: r[k] for k in fields}} for i, r in enumerate(ranked, 1)],
            "raw_top_k_ids": [r["document_id"] for r in raw], "final_ids": ids,
            "raw_recall": len(gold.intersection(raw_ids)) / len(gold) if answerable else None,
            "raw_reciprocal_rank": 1 / first_raw if first_raw else 0.0 if answerable else None,
            "recall": len(gold.intersection(ids)) / len(gold) if answerable else None,
            "reciprocal_rank": 1 / first if first else 0.0 if answerable else None,
            "returned_precision": len(gold.intersection(ids)) / len(ids) if answerable and ids else 0.0 if answerable else None,
            "full_recall": not missed and not error if answerable else None,
            "missed_relevant": known_misses, "unrelated_ids": [key for key in ids if key not in gold],
            "no_answer_false_retrieval": bool(ids) if case["answerability"] == "no_kb_answer" else None,
            "error": error}


def fraction(numerator, denominator):
    return {"numerator": round(numerator, 6), "denominator": denominator,
            "rate": round(numerator / denominator, 6) if denominator else None}


def summarize(rows):
    known = [r for r in rows if r["answerability"] in ANSWERABLE]
    absent = [r for r in rows if r["answerability"] == "no_kb_answer"]
    dynamic = [r for r in rows if r["answerability"] == "business_data_only"]
    return {
        "recall_at_4": fraction(sum(r["recall"] for r in known), len(known)),
        "mrr_at_4": fraction(sum(r["reciprocal_rank"] for r in known), len(known)),
        "full_recall_queries": fraction(sum(r["full_recall"] for r in known), len(known)),
        "returned_precision_macro": fraction(sum(r["returned_precision"] for r in known), len(known)),
        "no_answer_false_retrieval": fraction(sum(r["no_answer_false_retrieval"] for r in absent), len(absent)),
        "no_answer_outcomes": {"returned_irrelevant": sum(bool(r["final_ids"]) for r in absent),
                               "successful_empty": sum(not r["final_ids"] and not r["error"] for r in absent),
                               "exceptions": sum(bool(r["error"]) for r in absent)},
        "retrieval_exceptions": fraction(sum(bool(r["error"]) for r in rows), len(rows)),
        "diagnostics_before_coverage_filter": {
            "recall_at_4": fraction(sum(r["raw_recall"] for r in known), len(known)),
            "mrr_at_4": fraction(sum(r["raw_reciprocal_rank"] for r in known), len(known)),
            "no_answer_nonempty": fraction(sum(bool(r["raw_top_k_ids"]) for r in absent), len(absent)),
        },
        "missed_relevant_by_cause": dict(Counter(reason for r in known for reason in r["missed_relevant"].values())),
        "known_queries_with_extra_context": sum(bool(r["unrelated_ids"]) for r in known),
        "dynamic_diagnostics": {"questions": len(dynamic), "nonempty_results": sum(bool(r["final_ids"]) for r in dynamic)},
    }


def evaluate_cases(corpus, cases):
    methods = {}
    for method in METHODS:
        rows = []
        for case in cases:
            error = None
            try:
                # Full ranking is retained to distinguish cutoff from filtering.
                ranked = search(corpus, case["query"][:CONFIG["query_character_limit"]], max(1, len(corpus)), method=method)
            except Exception as exc:
                ranked, error = [], type(exc).__name__
            rows.append(score_case(case, ranked, error=error))
        methods[method] = {"metrics": summarize(rows), "results": rows,
                           "by_tag": {tag: summarize([r for r in rows if tag in r["tags"]])
                                      for tag in sorted({t for r in rows for t in r["tags"]})}}
    return methods


def development_preference(methods):
    def key(name):
        m = methods[name]["metrics"]
        return (-(m["retrieval_exceptions"]["numerator"] > 0),
                m["recall_at_4"]["rate"] or 0, -(m["no_answer_false_retrieval"]["rate"] or 0),
                m["mrr_at_4"]["rate"] or 0, name == "hybrid")
    return max(METHODS, key=key)


def verify_freeze(directory, freeze_path):
    if freeze_path is None:
        raise ValueError("Holdout requires --freeze; evaluate development and freeze settings first")
    frozen = read_json(freeze_path)
    if frozen.get("kind") != "retrieval_freeze" or frozen.get("development_preference") not in METHODS:
        raise ValueError("Not a retrieval freeze record")
    if frozen["identity"] != identity(directory):
        raise ValueError("Dataset, code or parameters changed since freeze; start a new development experiment")
    # Verify development bytes without loading its question/label objects.
    if digest(directory / "development.jsonl") != frozen["identity"]["dataset_files_sha256"]["development.jsonl"]:
        raise ValueError("Development data changed since freeze")
    return frozen


def run_evaluation(directory=DEFAULT_DATASET, split="development", *, freeze_path=None):
    directory = Path(directory)
    frozen = verify_freeze(directory, freeze_path) if split == "holdout" else None
    manifest, corpus, cases = load_split(directory, split)
    started = now()
    methods = evaluate_cases(corpus, cases)
    report = {"kind": "retrieval_evaluation", "version": "0.5.6", "split": split,
              "started_at": started, "completed_at": now(), "identity": identity(directory),
              "questions": len(cases), "groups": len({r["group_id"] for r in cases}), "knowledge_records": len(corpus),
              "label_review_status": dict(Counter(c["review"]["status"] for c in cases)),
              "provisional_labels": any(c["review"]["status"] != "approved" for c in cases),
              "methods": methods, "external_model_calls": 0,
              "scope": "Ranking inside shared portal metadata/coverage rules. Character n-grams are not embeddings. No answer generation or online-quality measurement."}
    if split == "development":
        report["development_preference"] = development_preference(methods)
    else:
        report["freeze_sha256"] = digest(freeze_path)
        report["frozen_at"] = frozen["created_at"]
        report["development_preference"] = frozen["development_preference"]
        report["selection_updated_from_holdout"] = False
    return report


def make_freeze(directory, development_report, rationale):
    report = read_json(development_report)
    if report.get("kind") != "retrieval_evaluation" or report.get("split") != "development":
        raise ValueError("Freeze requires a development report")
    current = identity(Path(directory))
    if report["identity"] != current:
        raise ValueError("Development report was made with different data, code or settings")
    if digest(Path(directory) / "development.jsonl") != current["dataset_files_sha256"]["development.jsonl"]:
        raise ValueError("Development data changed after evaluation")
    if any(report["methods"][m]["metrics"]["retrieval_exceptions"]["numerator"] for m in METHODS):
        raise ValueError("Resolve retrieval exceptions before freezing")
    if not rationale.strip():
        raise ValueError("Record the development decision rationale before holdout")
    return {"kind": "retrieval_freeze", "created_at": now(), "identity": current,
            "development_report_sha256": digest(development_report),
            "development_metrics": {m: report["methods"][m]["metrics"] for m in METHODS},
            "development_preference": development_preference(report["methods"]),
            "rationale": rationale, "parameters_tuned": False,
            "holdout_rankings_used_to_select": False,
            "selection_scope": "Development preference for comparison; the portal keeps its hybrid default."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    commands = parser.add_subparsers(dest="command", required=True)
    for split in ("development", "holdout"):
        command = commands.add_parser(split)
        command.add_argument("--output", type=Path, default=Path(f"runtime/retrieval/{split}.json"))
        if split == "holdout":
            command.add_argument("--freeze", type=Path, required=True)
    command = commands.add_parser("freeze")
    command.add_argument("--development-report", type=Path, required=True)
    command.add_argument("--rationale", required=True)
    command.add_argument("--output", type=Path, default=Path("runtime/retrieval/frozen.json"))
    args = parser.parse_args()
    if args.output.exists():
        parser.exit(2, "Output already exists; choose a fresh --output path before running another experiment.\n")
    try:
        if args.command == "freeze":
            report = make_freeze(args.dataset, args.development_report, args.rationale)
        else:
            report = run_evaluation(args.dataset, args.command, freeze_path=getattr(args, "freeze", None))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Preserve prior runs and freeze records; choose a new path to rerun.
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"Retrieval experiment failed: {error}\n")
    if args.command == "freeze":
        print(json.dumps({"output": str(args.output), "development_preference": report["development_preference"],
                          "frozen_at": report["created_at"]}, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps({"split": report["split"], "output": str(args.output), "provisional_labels": report["provisional_labels"],
                      "methods": {m: report["methods"][m]["metrics"] for m in METHODS},
                      "development_preference": report["development_preference"]}, ensure_ascii=False, indent=2))
    return 1 if any(report["methods"][m]["metrics"]["retrieval_exceptions"]["numerator"] for m in METHODS) else 0


if __name__ == "__main__":
    raise SystemExit(main())
