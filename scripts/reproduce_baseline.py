#!/usr/bin/env python3
"""Reconstruct the pre-iteration local implementation in a temporary directory."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def check_source(source_root, expected_files):
    return [relative for relative, expected_hash in expected_files.items()
            if not (source_root / relative).is_file()
            or hashlib.sha256((source_root / relative).read_bytes()).hexdigest() != expected_hash]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, help="Matching 2026-09-19 post-fix source snapshot; current portal sources are not compatible")
    args = parser.parse_args(argv)
    if args.source_root is None:
        parser.error("Historical reconstruction needs --source-root with the matching 2026-09-19 source snapshot (not bundled). For current checks run scripts/evaluate_agent.py.")
    original = json.loads((ROOT / "evals/results/after.json").read_text())
    mismatches = check_source(args.source_root, original["implementation_files"])
    if mismatches:
        parser.error("Historical source does not match the recorded hashes: " + ", ".join(mismatches))
    expected = json.loads((ROOT / "evals/results/before.json").read_text())
    with tempfile.TemporaryDirectory(prefix="support-baseline-") as directory:
        destination = Path(directory)
        for relative in original["implementation_files"]:
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args.source_root / relative, target)
        subprocess.run(["git", "apply", "--whitespace=nowarn", str(ROOT / "evals/baselines/pre_iteration.patch")], cwd=destination, check=True)
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
