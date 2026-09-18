#!/usr/bin/env python3
"""Run fixed synthetic support scenarios against a selected implementation.

The default run is fully local. Text checks are explicit acceptance rules,
not a semantic factuality judge or an estimate of production resolution rate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grade_turn(expected, actual):
    answer = actual["answer"].casefold()
    cited = {item["document_id"] for item in actual["citations"]}
    checks = {
        "route": actual["route"] == expected["route"],
        "required_points": all(
            any(term.casefold() in answer for term in alternatives)
            for alternatives in expected["required_points"]
        ),
        "forbidden_claims": not any(term.casefold() in answer for term in expected["forbidden"]),
        "required_evidence": set(expected["evidence"]).issubset(cited),
        "allowed_evidence": cited.issubset(set(expected["allowed_evidence"])),
    }
    return {"checks": checks, "passed": all(checks.values())}


def fraction(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "rate": round(numerator / denominator, 6) if denominator else None}


def summarize(results):
    turns = [turn for case in results for turn in case["turns"]]
    answerable = [t for t in turns if t["expected"]["route"] == "answer" and t["expected"]["evidence"]]
    generated = [t for t in turns if t["actual"]["route"] == "answer" and t["actual"]["citations"]]
    escalation = [t for t in turns if t["expected"]["route"] == "escalate"]
    multi = [r for r in results if len(r["turns"]) > 1]
    return {
        "scenario_pass": fraction(sum(r["passed"] for r in results), len(results)),
        "turn_pass": fraction(sum(t["passed"] for t in turns), len(turns)),
        "route_accuracy": fraction(sum(t["checks"]["route"] for t in turns), len(turns)),
        "answerable_acceptance": fraction(sum(t["passed"] for t in answerable), len(answerable)),
        "evidence_rule_violation": fraction(sum(not t["checks"]["allowed_evidence"] for t in generated), len(generated)),
        "escalation_recall": fraction(sum(t["actual"]["route"] == "escalate" for t in escalation), len(escalation)),
        "multi_turn_success": fraction(sum(r["passed"] for r in multi), len(multi)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-root", type=Path, default=PROJECT)
    parser.add_argument("--cases", type=Path, default=PROJECT / "evals/scenarios.jsonl")
    parser.add_argument("--corpus", type=Path, default=PROJECT / "support_agent/demo/corpus.jsonl")
    parser.add_argument("--output", type=Path, default=PROJECT / "runtime/evaluation.json")
    parser.add_argument("--label", default="working-tree")
    parser.add_argument("--provider", choices=["local", "openai"], default="local")
    parser.add_argument("--fail-on-regression", type=Path, help="Compare with an earlier JSON report; fail if a previously passing case now fails")
    args = parser.parse_args()
    sys.path.insert(0, str(args.agent_root.resolve()))
    from support_agent.agent import CustomerAgent
    from support_agent.config import AgentConfig

    cases, corpus = read_jsonl(args.cases), read_jsonl(args.corpus)
    by_id = {r["document_id"]: r for r in corpus}
    if len({c["id"] for c in cases}) != len(cases):
        raise SystemExit("Duplicate scenario IDs")
    results = []
    for case in cases:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.jsonl"
            rows = [by_id[key] for key in case["corpus_ids"]]
            path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
            config = AgentConfig.from_env(corpus_path=path, provider=args.provider)
            agent = CustomerAgent(config, today=date.fromisoformat(case["as_of"]))
            turns = []
            for turn in case["turns"]:
                started = time.perf_counter()
                error = None
                try:
                    actual = agent.respond(turn["query"], session_id=case["id"]).to_dict()
                except Exception as exc:
                    # Keep the failed task in the denominator. Do not record
                    # raw provider exceptions, which may contain request data.
                    error = type(exc).__name__
                    actual = {"answer": "", "route": "error", "citations": []}
                grade = grade_turn(turn["expected"], actual)
                if error:
                    grade["passed"] = False
                turns.append({"query": turn["query"], "expected": turn["expected"],
                              "actual": actual, **grade, "error": error,
                              "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)})
            results.append({"id": case["id"], "category": case["category"],
                            "passed": all(t["passed"] for t in turns), "turns": turns})
    manifest = {str(p.relative_to(args.agent_root)): digest(p)
                for p in sorted((args.agent_root / "support_agent").glob("*.py"))}
    report = {
        "label": args.label, "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider, "model": config.model if args.provider == "openai" else None,
        "knowledge_version": "synthetic-v2-neutral", "as_of_dates": sorted({c["as_of"] for c in cases}),
        "dataset_sha256": digest(args.cases), "corpus_sha256": digest(args.corpus),
        "grader_sha256": digest(Path(__file__)), "implementation_files": manifest,
        "scope": "Synthetic development regression suite; AI-authored labels await owner review. Not a held-out or production sample. Text checks are lexical acceptance rules, not factuality verification.",
        "api_cost": None, "api_tokens": None,
        "metrics": summarize(results),
        "categories": {key: summarize([r for r in results if r["category"] == key])
                       for key in sorted({r["category"] for r in results})},
        "failures": [r["id"] for r in results if not r["passed"]], "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"label": args.label, "metrics": report["metrics"], "failures": report["failures"]}, ensure_ascii=False, indent=2))
    if args.fail_on_regression:
        previous = json.loads(args.fail_on_regression.read_text(encoding="utf-8"))
        for key in ("dataset_sha256", "corpus_sha256", "grader_sha256", "provider", "as_of_dates"):
            if previous[key] != report[key]:
                raise SystemExit(f"Incomparable reports: {key} differs")
        old_pass = {r["id"] for r in previous["results"] if r["passed"]}
        regressions = old_pass.intersection(report["failures"])
        if regressions:
            raise SystemExit(f"Regressions: {sorted(regressions)}")


if __name__ == "__main__":
    main()
