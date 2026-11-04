"""Separate quoted conversation details from verified monetary claims."""

import json
import re
from decimal import Decimal


NUMBER = r"-?\d+(?:,\d{3})*(?:\.\d+)?"
MONEY = re.compile(rf"(?P<prefix_sign>[-−])?(?P<symbol>[$¥￥])\s*(?P<amount>{NUMBER})|(?P<value>{NUMBER})\s*(?P<unit>USD|CNY|美元|美金|人民币|元|块)", re.I)
BARE_MONEY = re.compile(rf"(?:余额|退款金额|到账金额|扣费|手续费|实付|可退金额|已用额度|剩余额度)(?:为|是|合计|总计|只有|还有|剩余|：|:|\s){{0,5}}\s*(?P<amount>{NUMBER})(?![\d.:：])")


def decimal(value):
    return Decimal(str(value).replace(",", ""))


def money_claims(text):
    for match in MONEY.finditer(text):
        currency = "USD" if (match['symbol'] == '$' or (match['unit'] or '').lower() in {'usd', '美元', '美金'}) else "CNY"
        amount = decimal(match['amount'] or match['value'])
        if match['prefix_sign']:
            amount = -abs(amount)
        yield match.start(), match.end(), (currency, amount)


def numeric_evidence(baseline, facts):
    """Tool integer units are storage values, not customer-facing dollar amounts."""
    amounts = {value for _, _, value in money_claims(baseline)}
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if type(item) is int and key.endswith('_units'):
                    amounts.add(('USD', Decimal(item) / 10000))
                elif type(item) is int and key.endswith('_cents'):
                    amounts.add(('CNY', Decimal(item) / 100))
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(facts)
    return amounts


def quoted_request(text, start, end, amount, customer_amounts):
    # A requested retained balance is not an approved refund/current balance.
    # Only explicitly attributed requests may quote a customer's monetary value.
    if amount not in customer_amounts:
        return False
    left = re.split(r'[，,。；;\n!?！？]', text[:start])[-1]
    right = re.split(r'[，,。；;\n!?！？]', text[end:])[0]
    clause = left + text[start:end] + right
    attributed = re.search(r'(?:你|您|用户|客户).{0,30}(?:希望|想|要求|申请|提出|表示|提到|反馈|保留|留下)|(?:希望|申请|要求).{0,12}(?:保留|留下)|(?:保留|留下).{0,30}(?:诉求|申请|要求)|(?:不再|不按|原先|之前).{0,12}(?:保留|留下|留)', clause)
    # A comma can separate "you requested a partial refund" from its retained
    # amount. Keep that attribution only for a continuation naming retention.
    sentence_prefix = re.split(r'[。；;\n!?！？]', text[:start])[-1]
    if not attributed and re.fullmatch(r'\s*(?:并|并且|同时)?(?:保留|留下|留)\s*', left):
        attributed = re.search(r'(?:你|您|用户|客户).{0,30}(?:希望|想|要求|申请|提出|表示)', sentence_prefix)
    asserted = re.search(r'(?:实际|当前)(?:账户)?余额|(?:可退|到账|扣费|实付|手续费)(?:金额)?(?:为|是)|(?:已|已经)(?:退款|退还|到账|扣费)|可以退|能够退|将退', clause)
    return bool(attributed and not asserted)


def current_debt_claim(text, start, end, amount, facts):
    """A debt's positive magnitude is not a positive balance or refund amount."""
    currency, value = amount
    if currency != 'USD' or value <= 0:
        return False
    balances = [tool.get('result', {}).get('balance_units') for tool in facts
                if tool.get('name') in {'get_account_overview', 'check_balance_adjustment'}
                and tool.get('status', 'ok') == 'ok']
    if not any(type(balance) is int and balance < 0 and -Decimal(balance) / 10000 == value for balance in balances):
        return False
    left = re.split(r'[，,。；;\n!?！？]', text[:start])[-1]
    right = re.split(r'[，,。；;\n!?！？]', text[end:])[0]
    clause = left + text[start:end] + right
    if re.search(r'退款|可退|到账|可用余额|(?:当前|实际)(?:账户)?余额|(?:已|已经)(?:充值|付款|支付|扣费)', clause):
        return False
    return bool(re.search(r'(?:欠款|欠费|负余额|补足|补齐)(?:金额|当前|本次|账户|需要|为|是|的|\s)*$', left)
                or re.match(r'\s*(?:的)?(?:欠款|欠费|负余额)', right))


def numeric_issues(answer, baseline, *, facts=None, context=None, query=''):
    facts, context = facts or [], context or {}
    approved = numeric_evidence(baseline, facts)
    customers = [query] + [m['content'] for m in context.get('conversation', []) if m.get('speaker') == 'customer']
    customer_amounts = {value for text in customers for _, _, value in money_claims(text)}
    issue = []
    claims = list(money_claims(answer))
    for start, end, amount in claims:
        if amount not in approved and not quoted_request(answer, start, end, amount, customer_amounts) and not current_debt_claim(answer, start, end, amount, facts):
            issue.append({'code': 'unsupported_amount', 'message': '新增金额缺少本轮业务依据；客户希望保留的金额只能作为其诉求复述，不能推算或确认可退金额', 'severity': 'critical'})
            break
    # A currency-labelled value was already checked with its currency and role.
    bare = [m for m in BARE_MONEY.finditer(answer)
            if not any(start <= m.start('amount') and end >= m.end('amount') for start, end, _ in claims)]
    if any(decimal(m['amount']) not in {value for _, value in approved} for m in bare):
        issue.append({'code': 'unsupported_amount', 'message': '余额、扣费或退款金额缺少当前业务依据', 'severity': 'critical'})

    def numbers(text):
        text = MONEY.sub('', text)
        text = re.sub(r'\b(?:gpt|claude|gemini|grok|deepseek|qwen)[A-Za-z0-9._:/-]*', '', text, flags=re.I)
        text = re.sub(r'^\s*\d+[.、)]\s*', '', text, flags=re.M)
        # ISO date separators are not minus signs. A Chinese date rendering
        # must retain the same numeric evidence as its database timestamp.
        text = re.sub(r'\b(\d{4})-(\d{2})-(\d{2})(?=T|\b)', r'\1 \2 \3', text)
        return {decimal(n) for n in re.findall(NUMBER, text)}

    # Conversation numbers can describe error codes, dates and request IDs.
    # They never expand the separately checked monetary evidence above.
    evidence = baseline + '\n' + json.dumps(facts, ensure_ascii=False) + '\n' + query + '\n' + json.dumps(context, ensure_ascii=False)
    if numbers(answer) - numbers(evidence):
        issue.append({'code': 'unsupported_number', 'message': '新增数字未出现在当前问题、公开对话或本轮查询证据中，需要复核', 'severity': 'critical'})
    return issue
