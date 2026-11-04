"""Short, evidence-based run receipts and reported model usage (admin only)."""
import math
import re


def valid_prices(prices):
    return isinstance(prices, dict) and len(prices) <= 50 and all(
        isinstance(model, str) and 0 < len(model) <= 160 and isinstance(rate, dict)
        and set(rate) == {'input_per_million', 'output_per_million', 'currency'}
        and isinstance(rate['currency'], str) and re.fullmatch(r'[A-Z]{3}', rate['currency'])
        and all(type(rate[k]) in (int, float) and math.isfinite(rate[k]) and rate[k] >= 0
                for k in ('input_per_million', 'output_per_million'))
        for model, rate in prices.items())


def usage_summary(runs, prices=None):
    totals = {'runs': len(runs), 'calls': 0, 'failed_calls': 0, 'retries': 0,
              'input_tokens': 0, 'output_tokens': 0, 'usage_missing_calls': 0,
              'model_elapsed_ms': 0, 'cost_by_currency': {}, 'unpriced_calls': 0}
    prices = prices or {}
    for run in runs:
        model = run.get('quality', {}).get('model', {})
        for call in model.get('calls', []):
            totals['calls'] += 1
            totals['failed_calls'] += not call.get('ok', False)
            totals['retries'] += call.get('attempt', 1) > 1
            totals['model_elapsed_ms'] += call.get('elapsed_ms', 0)
            usage = call.get('usage', {})
            inp = usage.get('input_tokens', usage.get('prompt_tokens'))
            out = usage.get('output_tokens', usage.get('completion_tokens'))
            if type(inp) is not int or type(out) is not int:
                totals['usage_missing_calls'] += 1
                continue
            totals['input_tokens'] += inp
            totals['output_tokens'] += out
            rate = prices.get(call.get('response_model')) or prices.get(model.get('requested_model'))
            if not rate:
                totals['unpriced_calls'] += 1
                continue
            currency = rate['currency']
            amount = (inp * rate['input_per_million'] + out * rate['output_per_million']) / 1_000_000
            totals['cost_by_currency'][currency] = totals['cost_by_currency'].get(currency, 0) + amount
    totals['cost_complete'] = not (totals['usage_missing_calls'] or totals['unpriced_calls'])
    totals['cost_basis'] = 'provider-reported tokens × administrator-supplied rates; estimates, not invoices'
    return totals


def run_receipt(run, prices=None):
    tools = run['tools']
    retrieval = next((t['result'].get('retrieval', {}) for t in tools if t['name'] == 'search_kb'), {})
    documents = next((t['result'].get('documents', []) for t in tools if t['name'] == 'search_kb'), [])
    ids = [e['id'] for e in run['evidence']]
    names = [t['name'] for t in tools if t['name'] != 'search_kb']
    model_summary = run.get('model_evidence_summary', '')
    if not isinstance(model_summary, str) or run['provider'] != 'openai':
        model_summary = ''
    cited = set(re.findall(r'\b[A-Z][A-Z_-]*-\d{3}\b', model_summary))
    if not cited.issubset(set(ids)):
        model_summary = ''
    parts = [f"分诊：{' / '.join(run['intents'])}；路由：{run['route']}。"]
    if retrieval:
        parts.append('检索：BM25 0.62 + 字符 2/3-gram 0.38，经问题类型和完整错误码过滤，最多 4 条；依据：' + ('＋'.join(ids) or '无匹配知识') + '。')
    parts.append('业务查询：' + (' → '.join(names) or '无需动态查询') + '；数据绑定当前工单客户。')
    model = run['quality'].get('model', {})
    fallback = run['quality'].get('model_fallback', False)
    if model.get('source') == 'policy':
        source = '财务固定模板'
        if any(c.get('stage') == 'support_intents' and c.get('ok') for c in model.get('calls', [])):
            source += '（真实模型分诊成功；模板用于账本操作）'
    else:
        source = '真实模型' if run['provider'] == 'openai' else '本地规则'
    source += '；发生模型回退' if fallback else '；未发生模型回退'
    parts.append('质检：' + ('通过' if run['quality']['passed'] else '待复核') + '；回复来源：' + source + '。')
    if model_summary:
        parts.append('模型依据摘要：' + model_summary)
    return {'summary': '\n'.join(parts), 'knowledge_ids': ids, 'tools': names,
            'documents': [{k: d[k] for k in ('document_id', 'score', 'lexical_score', 'semantic_ngram_score') if k in d} for d in documents],
            'retrieval': retrieval, 'usage': usage_summary([run], prices),
            'description': 'Evidence and execution summary; not hidden model reasoning.'}
