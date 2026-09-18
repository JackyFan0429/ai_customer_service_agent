#!/usr/bin/env python3
"""Reconstruct the pre-iteration local implementation in a temporary directory."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    expected = json.loads((ROOT / "evals/results/before.json").read_text())
    with tempfile.TemporaryDirectory(prefix="support-baseline-") as directory:
        destination = Path(directory)
        shutil.copytree(ROOT / "support_agent", destination / "support_agent",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "demo", "static"))
        subprocess.run(["git", "apply", str(ROOT / "evals/baselines/pre_iteration.patch")], cwd=destination, check=True)
        for relative, expected_hash in expected["implementation_files"].items():
            actual_hash = hashlib.sha256((destination / relative).read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                raise SystemExit(f"Baseline hash mismatch: {relative}")
        subprocess.run([
            sys.executable, str(ROOT / "scripts/evaluate_agent.py"),
            "--agent-root", str(destination), "--label", "reproduced-before-local-20260919",
            "--output", str(ROOT / "runtime/reproduced_before.json"),
            "--fail-on-regression", str(ROOT / "evals/results/before.json"),
        ], check=True)
        result = json.loads((ROOT / "runtime/reproduced_before.json").read_text())
        if result["metrics"] != expected["metrics"] or result["failures"] != expected["failures"]:
            raise SystemExit("Baseline outcome mismatch")


if __name__ == "__main__":
    main()
