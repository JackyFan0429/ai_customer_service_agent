#!/usr/bin/env python3
"""Compare filtering on owner-reviewed labels; published holdout is diagnostic."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluate_retrieval import load_split
from support_agent.desk.knowledge import retrieve
from support_agent.retrieval import search

FILES = ('support_agent/retrieval.py', 'support_agent/desk/knowledge.py',
         'support_agent/desk/topics.py', 'scripts/evaluate_reviewed_retrieval.py')


def fingerprint(dataset):
    return {'code': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in FILES},
            'data': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(dataset.iterdir()) if p.suffix in {'.json', '.jsonl'}}}


def measure(cases, retrieve_ids):
    rows = []
    for case in cases:
        ids = retrieve_ids(case['query'])
        gold = set(case['relevant_ids'])
        ranks = [i for i, key in enumerate(ids, 1) if key in gold]
        rows.append({'id': case['id'], 'expected': case['relevant_ids'], 'returned': ids,
                     'answerability': case['answerability'],
                     'recall': len(gold.intersection(ids)) / len(gold) if gold else None,
                     'mrr': 1 / ranks[0] if ranks else 0,
                     'precision': len(gold.intersection(ids)) / len(ids) if ids else 0})
    positive = [r for r in rows if r['recall'] is not None]
    absent = [r for r in rows if r['answerability'] == 'no_kb_answer']
    dynamic = [r for r in rows if r['answerability'] == 'business_data_only']
    return {'metrics': {
        'answerable_count': len(positive),
        'recall_at_4': sum(r['recall'] for r in positive) / len(positive),
        'mrr_at_4': sum(r['mrr'] for r in positive) / len(positive),
        'returned_precision_macro': sum(r['precision'] for r in positive) / len(positive),
        'fully_covered': sum(r['recall'] == 1 for r in positive),
        'no_answer_false_retrieval': {'count': sum(bool(r['returned']) for r in absent), 'total': len(absent)},
        'dynamic_queries_with_static_evidence': sum(bool(r['returned']) for r in dynamic),
    }, 'cases': rows}


def evaluate(dataset, split, freeze=None):
    signature = fingerprint(dataset)
    if split == 'holdout':
        if not freeze or freeze.get('split') != 'development' or freeze.get('fingerprint') != signature:
            raise ValueError('Run development first and pass its unchanged report with --freeze')
    manifest, corpus, cases = load_split(dataset, split)
    if any(r['review']['status'] != 'approved' for r in cases):
        raise ValueError('All labels must be explicitly approved before this evaluation')
    baseline = lambda q: [d['document_id'] for d in search(corpus, q, 4) if d['query_term_coverage'] >= .12]
    updated = lambda q: [d['document_id'] for d in retrieve(corpus, q)['documents']]
    return {'release': '0.5.9', 'split': split, 'dataset_id': manifest['dataset_id'],
            'fingerprint': signature,
            'interpretation': 'Regression diagnostics on already reviewed/published questions; not blind validation or an answer-quality score.',
            'configuration': 'Unchanged BM25 0.62 + character 2/3-gram 0.38. Compare old top-4 coverage >= 0.12 with topic/capability/identifier filtering. No embedding calls.',
            'baseline': measure(cases, baseline), 'updated': measure(cases, updated)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('split', choices=('development', 'holdout'))
    parser.add_argument('--dataset', type=Path, default=ROOT / 'evals/retrieval/lumen-v3')
    parser.add_argument('--freeze', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; use a new path to preserve evidence')
    try:
        report = evaluate(args.dataset, args.split, json.loads(args.freeze.read_text()) if args.freeze else None)
    except ValueError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: report[k]['metrics'] for k in ('baseline', 'updated')}, indent=2))


if __name__ == '__main__':
    main()
