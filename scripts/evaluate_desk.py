#!/usr/bin/env python3
"""Run the local business-backed support workflow evaluation."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support_agent.desk.evaluation import evaluate

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runtime/desk_evaluation.json"))
    args = parser.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"passed": report["passed"], "total": report["total"], "output": str(args.output),
                      "failed": [r for r in report["results"] if not r["passed"]]}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] == report["total"] else 1)
