#!/usr/bin/env python3
"""Dependency-free BM25 + character n-gram hybrid search baseline."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


WORD_RE = re.compile(r"[a-z][a-z0-9_.+-]*|\d{3}|[\u4e00-\u9fff]", re.I)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--category")
    parser.add_argument("--product")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def terms(text: str) -> list[str]:
    raw = str(text).casefold()
    base = WORD_RE.findall(raw)
    chinese = "".join(ch for ch in raw if "\u4e00" <= ch <= "\u9fff")
    base.extend(chinese[index : index + 2] for index in range(max(0, len(chinese) - 1)))
    return base


def char_features(text: str) -> Counter[str]:
    normalized = re.sub(r"\s+", "", str(text).casefold())
    features: Counter[str] = Counter()
    for size in (2, 3):
        features.update(normalized[index : index + size] for index in range(max(0, len(normalized) - size + 1)))
    return features


def searchable_text(row: dict[str, Any]) -> str:
    metadata = [
        *row.get("keywords", []),
        *row.get("categories", []),
        *row.get("products", []),
        *row.get("clients", []),
    ]
    return " ".join([str(row.get("title", "")), str(row.get("text", "")), *map(str, metadata)])


def cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    common = set(left).intersection(right)
    dot = sum(left[key] * right[key] for key in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def search(
    corpus: list[dict[str, Any]],
    query: str,
    top_k: int,
    category: str | None = None,
    product: str | None = None,
) -> list[dict[str, Any]]:
    filtered = [
        row
        for row in corpus
        if (not category or category in row.get("categories", []))
        and (not product or product in row.get("products", []))
    ]
    if not filtered:
        return []

    document_terms = [terms(searchable_text(row)) for row in filtered]
    lengths = [len(values) for values in document_terms]
    avg_len = sum(lengths) / len(lengths) if lengths else 1.0
    doc_freq: Counter[str] = Counter()
    for values in document_terms:
        doc_freq.update(set(values))
    query_terms = terms(query)
    query_features = char_features(query)
    n_docs = len(filtered)
    raw_scores: list[tuple[float, float, dict[str, Any]]] = []

    for row, values, doc_len in zip(filtered, document_terms, lengths):
        frequencies = Counter(values)
        bm25 = 0.0
        for token in query_terms:
            frequency = frequencies[token]
            if not frequency:
                continue
            df = doc_freq[token]
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * doc_len / max(avg_len, 1))
            bm25 += idf * (frequency * 2.5 / denominator)
        semantic = cosine(query_features, char_features(searchable_text(row)))
        raw_scores.append((bm25, semantic, row))

    max_bm25 = max((item[0] for item in raw_scores), default=1.0) or 1.0
    results: list[dict[str, Any]] = []
    for bm25, semantic, row in raw_scores:
        lexical = bm25 / max_bm25
        base = 0.62 * lexical + 0.38 * semantic
        authority_boost = 0.0
        if row.get("precedence") == "P1" and base > 0.03:
            query_set = set(query_terms)
            metadata_set = set(
                terms(
                    " ".join(
                        [
                            str(row.get("title", "")),
                            *map(str, row.get("keywords", [])),
                            *map(str, row.get("categories", [])),
                            *map(str, row.get("products", [])),
                            *map(str, row.get("clients", [])),
                        ]
                    )
                )
            )
            overlap = len(query_set.intersection(metadata_set)) / max(1, len(query_set))
            authority_boost = round(min(0.22, 0.08 + 0.18 * overlap), 6)
        score = base + authority_boost
        if score <= 0:
            continue
        results.append(
            {
                "score": round(score, 6),
                "lexical_score": round(lexical, 6),
                "semantic_ngram_score": round(semantic, 6),
                "authority_boost": authority_boost,
                **row,
            }
        )
    # A relevant official result must be presented before historical evidence.
    # The threshold prevents a weakly related official page from eclipsing a
    # strongly matching case merely because it has P1 authority.
    results.sort(
        key=lambda row: (
            1 if row.get("precedence") == "P1" and row["score"] >= 0.32 else 0,
            row["score"],
        ),
        reverse=True,
    )
    return results[: max(1, top_k)]


def main() -> None:
    args = parse_args()
    corpus = read_jsonl(Path(args.corpus))
    results = search(corpus, args.query, args.top_k, args.category, args.product)
    print(json.dumps({"query": args.query, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
