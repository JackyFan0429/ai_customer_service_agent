#!/usr/bin/env python3
"""Command-line wrapper for the reusable hybrid retriever."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from support_agent.retrieval import read_jsonl, search


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--category")
    parser.add_argument("--product")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    corpus = read_jsonl(Path(args.corpus))
    results = search(corpus, args.query, args.top_k, args.category, args.product)
    print(json.dumps({"query": args.query, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
