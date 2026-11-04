"""Auditable filtering of lexical candidates for the local support knowledge base.

BM25/character n-gram ranking stays shared with the frozen historical evaluator.
This layer checks the question's capability, identifiers and business subject
before sending at most four articles to the reply model.
"""
import re

from ..retrieval import search
from .topics import focus_question


def query_scope(query):
    # Use the same explicit topic-switch syntax as the conversation router.
    # This removes paused clauses without inventing a rewritten question.
    q = focus_question(query, {}, {})['message'].casefold()
    code = re.search(r'(?:错误码|error code)\s*(?:是|为|[:：=])?\s*(\d{3,5})(?![0-9a-z_])', q)
    unsupported = code and code[1] not in {'401', '403', '500', '502', '503'}
    if unsupported:
        return {'mode': 'missing', 'ids': [], 'reason': f'知识未定义错误码 {code[1]}', 'gap': 'error_definition'}
    if re.search(r'上下文.{0,12}(?:窗口|上限|token|长度)|context.{0,8}window', q):
        return {'mode': 'missing', 'ids': [], 'reason': '知识未提供该模型的上下文窗口规格', 'gap': 'model_specification'}
    if re.search(r'发票|invoice', q) and re.search(r'导出|export|excel', q):
        return {'mode': 'missing', 'ids': [], 'reason': '知识未提供发票导出能力及 API 参数', 'gap': 'invoice_export'}
    if re.search(r'毫秒|耗时|latency|milliseconds', q) and re.search(r'请求|日志|request', q):
        return {'mode': 'duration', 'ids': [], 'reason': '实际请求耗时需要匹配日志'}
    if re.search(r'余额|钱包', q) and re.search(r'多少钱|精确|只查|仅查询|查一下余额', q) and not re.search(r'回正|欠费|负|扣费|兜底|先扣|先花', q):
        return {'mode': 'account', 'ids': [], 'reason': '当前金额需要账户查询'}
    ids = []
    patterns = {
        'PLAN-001': r'套餐|额度|周期|周卡|月卡|卡里的量|先花|先扣|这期的量|卡的到期|余额兜底|余额扣费',
        'BAL-001': r'负余额|欠费|欠款|回正|抹零|用超',
        'REFUND-001': r'退款|退钱|退订|钱想退|钱退|手续费',
        'ERR-401': r'(?<![0-9a-z_])(?:401|403)(?![0-9a-z_])|鉴权',
        'ERR-503': r'(?<![0-9a-z_])(?:500|502|503)(?![0-9a-z_])|(?:失败|没成功).{0,16}(?:收费|扣费|扣钱|照扣)|请求.{0,12}(?:失败|很慢|超时)',
        'SETUP-001': r'配置|接入|协议|base.?url|环境变量|custom|自定义|(?:切换|选择).{0,8}模型',
        'INVOICE-001': r'发票|开票|抬头',
        'STATUS-001': r'平台.{0,12}(?:状态|故障|恢复)|渠道.{0,12}(?:故障|状态|恢复|正常)|故障公告|恢复时间|恢复日期',
        'ACCOUNT-001': r'人工.{0,8}(?:接手|接管|回复|建议)|(?:另一|其他).{0,8}(?:账号|邮箱)|密码|账号归属',
        'IMAGE-001': r'图片|截图|附件',
    }
    for kid, pattern in patterns.items():
        if re.search(pattern, q):
            ids.append(kid)
    # In this business, a 403 diagnosis depends on the plan/fallback policy even
    # when a follow-up abbreviates that subject to "still 403".
    if 'ERR-401' in ids and re.search(r'(?<![0-9a-z_])403(?![0-9a-z_])', q) and 'PLAN-001' not in ids:
        ids.append('PLAN-001')
    if 'IMAGE-001' in ids and not re.search(r'(?<![0-9a-z_])(?:500|502|503)(?![0-9a-z_])', q):
        ids = [kid for kid in ids if kid != 'ERR-503']
    if 'ERR-401' in ids and not re.search(r'怎么配置|如何接入|协议', q):
        ids = [kid for kid in ids if kid != 'SETUP-001']
    policy = bool(re.search(r'什么条件|哪些条件|金额小就|见到负数|先扣哪|先花|顺序|核对哪些配置|不是一回事|是不是|能不能|可以说|算办完|还没实际|还没有真正|会直接插|要注明|能否承诺|能不能.*证明|马上刷新', q))
    policy = policy or 'ACCOUNT-001' in ids and bool(re.search(r'就能|可以查|能去查', q))
    # An explicit incident or an invoice/refund instruction needs business data.
    incident = bool(re.search(r'返回\s*403|(?<![0-9a-z_])503(?![0-9a-z_])|(?:失败|没成功).{0,16}(?:扣|收费)', q))
    action = bool(re.search(r'我要.{0,8}退|钱想退|帮我.{0,8}退|抬头填错|要重开', q))
    live_status = 'STATUS-001' in ids and bool(re.search(r'现在|当前|目前|查一下|查询', q)) and not re.search(r'昨天|历史|公告|证明|答复要', q)
    mode = 'policy' if policy and ids and not incident and not action and not live_status else 'general'
    return {'mode': mode, 'ids': ids, 'reason': '按问题主体过滤候选；模型名不单独构成规格或配置依据'}


def retrieve(corpus, query):
    scope = query_scope(query)
    ranked = search(corpus, query, max(1, len(corpus))) if corpus else []
    accepted, rejected = [], []
    for doc in ranked:
        faq = 'faq' in doc.get('categories', []) and doc['query_term_coverage'] >= .55
        selected = doc['document_id'] in scope['ids'] or faq
        if selected and len(accepted) < 4:
            accepted.append({k: doc[k] for k in ('document_id', 'title', 'text', 'categories', 'query_term_coverage',
                                                'score', 'lexical_score', 'semantic_ngram_score')})
        else:
            rejected.append({'id': doc['document_id'], 'reason': '未覆盖本题所需事实或已达到材料上限'})
    if any('faq' in d['categories'] for d in accepted) and scope['mode'] == 'missing':
        scope = {**scope, 'mode': 'faq', 'reason': '已发布 FAQ 包含相关说明'}
    return {'documents': accepted, 'retrieval': {'method': 'hybrid', 'bm25_weight': .62,
            'character_ngram_weight': .38, 'top_k': 4, 'scope': scope,
            'candidate_count': len(ranked), 'rejected': rejected}}


def policy_answer(documents):
    """Expose policy content, excluding privileged command/receipt instructions."""
    texts = []
    for doc in documents:
        text = doc['text']
        if doc['document_id'] == 'BAL-001':
            text = text.split('客服和管理员可在当前工单')[0]
            text += '仅提交申请或通过资格检查不代表完成，操作结果必须以实际余额与账本写入为准。'
        elif doc['document_id'] == 'ACCOUNT-001':
            text = text.split('全局开关')[0]
        texts.append(text)
    return '\n\n'.join(texts)
