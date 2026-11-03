#!/usr/bin/env python3
"""Run the local business-backed support workflow evaluation."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support_agent.desk import storage, tools
from support_agent.desk.evaluation import evaluate


def parse_as_of(value):
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--as-of requires an ISO timestamp with a UTC offset") from error
    if instant.utcoffset() is None:
        raise argparse.ArgumentTypeError("--as-of requires an explicit UTC offset, e.g. +11:00")
    return instant.astimezone(timezone.utc)


def run_evaluation(as_of=None):
    """Freeze business dates only in this offline CLI process; timers stay real."""
    if as_of is None:
        report = evaluate()
    else:
        instant = parse_as_of(as_of.isoformat())

        class EvaluationDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz) if tz is not None else instant.astimezone().replace(tzinfo=None)

        # Seed dates, expiry checks and request/ledger lookback windows must use
        # the same instant. The website keeps using its unmodified wall clock.
        with patch.object(storage, "datetime", EvaluationDateTime), patch.object(tools, "datetime", EvaluationDateTime):
            report = evaluate()
    report["as_of"] = as_of.astimezone(timezone.utc).isoformat() if as_of is not None else None
    report["clock_mode"] = "fixed" if as_of is not None else "wall"
    report["created_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runtime/desk_evaluation.json"))
    parser.add_argument("--as-of", type=parse_as_of, help="Fixed business time for offline evaluation; include a timezone offset")
    args = parser.parse_args()
    report = run_evaluation(args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"passed": report["passed"], "total": report["total"], "output": str(args.output),
                      "failed": [r for r in report["results"] if not r["passed"]]}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] == report["total"] else 1)
