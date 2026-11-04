"""Evidence-first support workflow inspired by observable export events."""

from __future__ import annotations

import json
import re
import time

from ..providers import GenerationError
from .model import DeskModel
from .evidence import numeric_issues
from .topics import focus_question, remember_topic, topic_history
from .storage import Database, now
from .tools import LocalBusinessTools, money
from .request_context import QUERY_KEYS, select_context, request_id
from .billing import refresh_subscriptions
from .knowledge import query_scope, policy_answer


INTENT_LABELS = {"quota": "套餐额度", "balance": "余额核验", "refund": "退款申请", "invoice": "发票",
                 "technical": "请求排障", "status": "平台状态", "configuration": "接入配置", "account": "账号管理",
                 "resolved": "确认解决", "resolution_check": "确认恢复", "greeting": "问候", "unknown": "补充信息"}
RULES = {
    "quota": r"套餐|额度|周期|月卡|周卡|刷新",
    "balance": r"余额|欠费|回正|充值",
    "refund": r"退款|退钱|钱想退|退订|退还|全退(?!出)|部分退|手续费",
    "invoice": r"发票|开票|抬头",
    "technical": r"耗时|毫秒|报错|错误|不能用|用不了|没成功|失败|扣费|照扣|超时|很慢|卡顿|断开|401|403|500|502|503|error|reconnect|扣了多少钱|扣款了吗",
    "status": r"平台.{0,10}(状态|故障|正常|恢复)|渠道.{0,10}(状态|故障|恢复)|宕机|服务状态",
    "configuration": r"配置|接入|协议|base.?url|endpoint|怎么连接|接口地址|模型.{0,12}(?:切换|选择|自定义|custom)|(?:切换|选择).{0,12}模型|custom",
    "account": r"密码|改邮箱|修改邮箱|封号|封禁|转人工|找人工|(?:需要|想找|联系|帮我找)(?:人工)?客服",
}
SECRET_RE = re.compile(r"\b(?:sk|rk|pk|key)[_-][A-Za-z0-9_-]{12,}\b|\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_.-]+", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def scrub(text: str) -> str:
    text = SECRET_RE.sub("[密钥已隐藏]", str(text))
    text = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)\S+", r"\1[已隐藏]", text)
    text = re.sub(r"(?i)((?:password|密码|api[_ -]?key|token)\s*[=:：]\s*)[^\s,;，；]{4,}", r"\1[已隐藏]", text)
    return text


def local_intents(query: str, context: dict) -> list[str]:
    focus = focus_question(query, context, RULES)
    if focus['ambiguous']:
        return ['unknown']
    q = focus['message'].strip()
    recovery = re.search(r"已解决|解决了|恢复了|(?:已经|现已|已)恢复正常|正常了|(?:可以|能够|能)(?:正常)?(?:使用|用)了|好了", q)
    negative = re.search(r"(?:还|仍|尚|依然)?(?:没|没有|未)(?:有|能)?(?:解决|恢复|好|正常|核实|核验|确认|处理|到账)|(?:不是|并非).{0,4}(?:可以|能够|能用|正常|恢复)|还是|仍然|不能用|不行|不好(?!意思)|但是|不过|另外|还有|[？?]", q)
    if recovery and not negative:
        multiple = len(focus['known_topics']) > 1
        all_done = re.search(r'(?:结束|关闭).{0,6}工单|结单|(?:全部|所有|都).{0,8}(?:解决|好了|恢复|正常)', q)
        if multiple and not all_done:
            return ['resolution_check']
        return ["resolution_check" if re.search(r"应该|好像|似乎|可能|貌似|也许", q) else "resolved"]
    if re.fullmatch(r"(?:好的[，,]?)?(?:已经|现在)?(?:解决了|可以用了|恢复了|好了|正常了|已解决)[，,！!。\s]*(?:谢谢)?[！!。\s]*", q):
        return ["resolved"]
    found = list(focus['intents'])
    if request_id(q) and 'technical' not in found and not focus['excluded_intents'] and not any(i in found for i in ('refund', 'invoice')):
        found.append('technical')
    active = context.get("active_intents", context.get("intents", []))
    if "refund" in active and set(found).issubset({"balance", "quota", "status"}) and re.search(r"进度|多久|什么时候|哪一步|有结果|登记|那笔|重新提交|再开工单", q) and not re.search(r"另外|换个问题|先不|不问退款", q):
        found.append("refund")
    if not found and not focus['explicit_switch'] and re.search(r"还是|仍然|进度|多久|什么时候|刚才|上面|那个|催|没到|没有收到|照做|试过|没变化|没改善|依旧|一样|哪一步|有结果|重新提交|再开工单", q):
        found = [i for i in active if i not in {"resolved", "resolution_check", "greeting", "unknown"}]
    if not found and re.fullmatch(r"你好|您好|hi|hello|谢谢|好的|收到|你是谁[？?]?", q, re.I):
        found = ["greeting"]
    return [i for i in found if i not in focus['excluded_intents']] or ["unknown"]


def quality_check(answer: str, baseline: str, *, facts: list[dict] | None = None, context: dict | None = None, query: str = "") -> dict:
    issues = []
    if SECRET_RE.search(answer):
        issues.append({"code": "secret", "message": "回复包含疑似密钥", "severity": "critical"})
    for phrase in ["已退款", "已经退款", "保证到账", "一定到账", "已回正", "已经回正", "已重置", "已关闭工单", "已重开发票", "已修改发票", "已开具", "已发送发票"]:
        def asserted(text):
            for match in re.finditer(re.escape(phrase), text):
                prefix = re.split(r"[，,。；;\n]", text[:match.start()])[-1]
                if not re.search(r"(?:不能|无法|不会|不|尚未|没有|未)(?:确认|承诺|保证|说)?\s*[\"“]?$", prefix):
                    return True
            return False
        if asserted(answer) and not asserted(baseline):
            issues.append({"code": "unsupported_action", "message": f"缺少操作依据：{phrase}", "severity": "critical"})
    if re.search(r"内部备注|password_hash|eligible=|evidence_summary|search_kb|fix_negative_balance|check_balance_adjustment|check_platform_status|get_(?:account_overview|subscriptions|api_keys|orders|invoices|recent_requests|user_ticket_history)|\b[A-Z][A-Z_-]*-\d{3}\b|BM25|/recharge", answer):
        issues.append({"code": "internal_disclosure", "message": "回复包含内部字段或工具名", "severity": "critical"})
    if re.search(r'我(?:已|已经)?(?:看到|看过|查看了|识别了)(?:这张)?截图|从截图(?:中)?(?:可以|能)(?:看出|看到)', answer):
        issues.append({'code': 'unsupported_image', 'message': '当前没有图片内容，不能声称识别了截图', 'severity': 'critical'})
    issues.extend(numeric_issues(answer, baseline, facts=facts, context=context, query=query))
    return {"passed": not issues, "issues": issues,
            "checks": ["账户范围由服务端绑定", "金额与状态有查询依据", "未承诺未执行的操作", "内部信息不进入客户回复"],
            "reviewed_at": now()}


def technical_followup(query, conversation):
    """Ask only for missing customer details, including after a model outage."""
    messages = [m["content"] for m in conversation.get("conversation", []) if m["speaker"] == "customer"] + [query]
    supplied = "\n".join(messages)
    has_time = bool(re.search(r"\d{1,2}[:：]\d{2}|刚才|分钟前|小时前|时间.{0,12}(?:已经|已|发过|提供)", supplied))
    has_error = bool(re.search(r"(?:完整.{0,4}(?:报错|错误)|(?:报错|错误).{0,4}(?:全文|文字)|error)\s*[是为:：]|upstream unavailable|rate.limit|insufficient.quota", supplied, re.I))
    if re.search(r"完整错误已经发过|完整报错已经发过", supplied):
        has_error = True
    missing = ([] if has_time else ["发生时间及所在时区"]) + ([] if has_error else ["完整错误文字"])
    if missing:
        return "已收到本工单中提供的信息；只需补充尚缺的" + "和".join(missing) + "，已提供的客户端、模型和尝试步骤无需重复。"
    if re.search(r"没有.{0,6}(?:请求编号|请求ID|request.?id)|(?:请求编号|请求ID|request.?id).{0,6}(?:没有|找不到)", supplied, re.I):
        return "已收到发生时间和完整报错，也了解到你没有请求编号，无需重复提供；现有查询不足以定位这次请求，交由人工结合已提供的信息继续核验。"
    return "已收到发生时间和完整报错，无需重复提供；如能找到请求编号可补充以便核对，没有也可由人工结合已有信息继续排查。"


def clarify_missing(query, conversation):
    if re.search(r'无法提供|没法复制|无法复制|看不清|没有更多信息', query):
        return '已保留本工单提供的信息；当前无法读取图片内容，这部分转交人工继续核查，无需重复提交同样内容。', True
    focus = conversation.get('current_topic', {})
    prior = [] if focus.get('explicit_switch') else [m['content'] for m in conversation.get('conversation', []) if m['speaker'] in {'customer', 'human'}]
    supplied = '\n'.join(prior + [focus.get('reference_question', ''), query])
    missing = []
    if not re.search(r'Codex|Claude Code|Cursor|客户端(?:是|为|[:：])', supplied, re.I):
        missing.append('使用的客户端')
    if not re.search(r'\b(?:gpt|claude|grok|gemini|deepseek)[-\w.]+|模型(?:是|为|[:：])', supplied, re.I):
        missing.append('模型名称')
    if not re.search(r'(?:error|错误|报错)\s*(?:为|是|[:：=])\s*(?!什么|怎么|哪个|否|不是|多少|为何)\S+|[a-z]+_[a-z_]+|完整(?:错误|报错)(?:文字)?(?:已经|已)发过', supplied, re.I):
        missing.append('完整错误文字')
    prefix = '当前没有可读取的图片内容，不能直接查看截图。' if re.search(r'截图|图片|附件', supplied) else '已收到本工单提供的信息。'
    if missing:
        return prefix + '只需补充尚缺的' + '、'.join(missing) + '；已提供的信息无需重复。请遮盖密码、密钥和无关个人信息。', False
    return prefix + '已保留客户端、模型与报错信息，交由人工继续核查，无需重复提供。', True


class SupportWorkflow:
    def __init__(self, db: Database, model: DeskModel | None = None):
        self.db, self.model = db, model

    def conversation_context(self, ticket, message, state):
        # Only published messages from this ticket; drafts/internal events and
        # other users' conversations never enter a model request.
        rows = self.db.all("SELECT role,content,created_at,retracted_at,request_context_json FROM messages WHERE ticket_id=? AND id<? AND visibility='public' AND role IN ('customer','assistant','human') ORDER BY id DESC LIMIT 25", (ticket["id"], message["id"]))
        conversation, remaining = [], 16000
        truncated = len(rows) > 24
        for row in rows[:24]:
            content = "[消息已撤回，不作为事实依据]" if row["retracted_at"] else scrub(row["content"])
            if remaining <= 0:
                truncated = True
                break
            limit = min(remaining, 2500)
            if len(content) > limit:
                content = content[:limit] + "…[已截断]"
                truncated = True
            remaining -= len(content)
            conversation.append({"speaker": {"assistant": "ai"}.get(row["role"], row["role"]),
                                 "content": content, "created_at": row["created_at"], "request_context": {} if row["retracted_at"] else json.loads(row.get("request_context_json") or "{}")})
        conversation.reverse()
        return {"subject": scrub(ticket["subject"]), "conversation": conversation,
                "history_truncated": truncated, "previous_intents": state.get("active_intents", state.get("intents", [])),
                "human_priority": ticket["mode"] == "human" or bool(ticket["human_until"] and ticket["human_until"] > now())}

    def build(self, ticket: dict, message: dict) -> dict:
        started = time.perf_counter()
        # Scheduled business maintenance runs before evidence collection; tools remain read-only.
        refresh_subscriptions(self.db, ticket['user_id'])
        config = self.db.settings()
        query = scrub(message["content"])
        context = json.loads(ticket["context_json"])
        conversation = self.conversation_context(ticket, message, context)
        if 'topic_history' not in context:
            # Upgrade existing tickets from their bounded, published customer
            # history. Never infer actions or facts from an old AI draft.
            recovered = {}
            for old in conversation['conversation']:
                if old['speaker'] == 'customer':
                    previous = local_intents(old['content'], recovered)
                    history = remember_topic(recovered, old['content'], previous)
                    recovered = {'topic_history': history, 'active_intents': previous}
            context['topic_history'] = recovered.get('topic_history', topic_history(context))
        focus = focus_question(query, context, RULES)
        conversation['current_topic'] = focus
        selection = select_context({**message, 'content': query}, conversation, context, focus)
        conversation['request_context'] = selection
        model = DeskModel(self.model.provider) if isinstance(self.model, DeskModel) else self.model
        intents = local_intents(query, context)
        if intents == ['unknown'] and not focus['explicit_switch'] and 'technical' in context.get('active_intents', []) and (selection.get('start_utc') or selection.get('time_issue')):
            intents = ['technical']
        provider = "local"
        warnings: list[str] = []
        blocking_warnings: list[str] = []
        model_fallback = False
        model_classified = False
        if model:
            try:
                model_intents = model.classify(query, conversation)
                if focus['ambiguous']:
                    model_intents = []
                elif focus['explicit_switch']:
                    allowed = set(focus['intents'])
                    model_intents = [i for i in model_intents if i not in focus['excluded_intents']
                                     and (not allowed or i in allowed)]
                if "refund" in intents and not re.search(RULES["status"], query, re.I):
                    model_intents = [i for i in model_intents if i != "status"]
                if re.search(r'兜底|余额扣费', focus['message']) and not re.search(RULES['configuration'], focus['message'], re.I):
                    model_intents = [i for i in model_intents if i != 'configuration']
                # Explicit policy-sensitive intents cannot be removed by a model rewrite.
                if intents not in (["resolved"], ["resolution_check"]):
                    intents = list(dict.fromkeys([i for i in intents if i != "unknown"] + [i for i in model_intents if i != "resolved"])) or intents
                model_classified = True
            except (GenerationError, KeyError, TypeError):
                model_fallback = True
                warnings.append("模型分诊不可用，已使用本地规则和业务查询生成回复")
        tools = LocalBusinessTools(self.db, ticket["user_id"], ticket["id"], max_calls=config["max_tool_calls"])

        def call(name, **args):
            try:
                return tools.call(name, **args)
            except (ValueError, RuntimeError):
                warning = f"{name} 未完成，缺失信息需人工核验"
                warnings.append(warning)
                blocking_warnings.append(warning)
                return {}

        parts, handoffs, actions, evidence = [], [], [], []
        scope = query_scope(focus["message"] or query)
        knowledge_answer = False
        if intents == ["resolved"]:
            parts.append("收到，感谢确认！这个问题已标记为解决，后续有新情况可以继续在本工单留言。")
            actions.append({"type": "close_ticket", "reason": "用户明确确认问题已解决"})
        elif intents == ["resolution_check"]:
            if len(focus['known_topics']) > 1:
                parts.append("收到你的恢复反馈。本工单讨论过多个问题，请确认只是当前问题恢复，还是所有问题都已解决；确认全部完成后再关闭工单，避免遗漏其他事项。")
            else:
                parts.append("没关系。你说现在应该已经恢复，我先不重复排障步骤。方便确认一下，现在是否已经可以正常使用？确认后我再标记这个问题已解决。")
        elif intents == ["greeting"]:
            parts.append("不客气。有新的情况可以继续在这张工单里告诉我。" if conversation["conversation"] and re.search(r"谢谢|好的|收到", query) else "你好，我是 Lumen 客服助手。我可以查询你的套餐、订单和请求记录，也可以协助排障或转交人工。")
        else:
            retrieval_query = '，'.join(filter(None, [focus['reference_question'], focus['message']])) or query
            retrieved = call("search_kb", query=retrieval_query)
            docs = retrieved.get("documents", [])
            scope = retrieved.get("retrieval", {}).get("scope", scope)
            evidence = [{"id": d["document_id"], "title": d["title"]} for d in docs]
            if scope['mode'] == 'missing':
                parts.append(scope['reason'] + '，目前无法确认。我会为你对接人工进一步核实，无需另开工单。')
                handoffs.append(scope['reason'] + '，人工核实资料后继续答复')
                intents = ['unknown']
            elif scope['ids'] == ['IMAGE-001'] and re.search(r'占位|附件|截图|看图|图像|图片', query):
                clarification, escalate = clarify_missing(query, conversation)
                parts.append(clarification)
                if escalate:
                    handoffs.append('当前没有图片内容，人工结合已有文字信息核查')
                intents = ['unknown']
            elif scope['mode'] in {'policy', 'faq'}:
                if docs:
                    parts.append(policy_answer(docs))
                    knowledge_answer = True
                else:
                    parts.append('当前没有已发布且有效的相关规则资料，我会为你对接人工核实。')
                    handoffs.append('缺少有效知识依据')
                intents = ['unknown']
            elif scope['mode'] == 'account':
                account = call('get_account_overview')
                if 'balance_units' in account:
                    parts.append(f"本次查询到的账户余额是 {money(account['balance_units'])}。")
                intents = ['unknown']
                knowledge_answer = True
            elif scope['mode'] == 'duration':
                args = {k: v for k, v in selection.items() if k in QUERY_KEYS and v is not None}
                logs = {} if selection.get('time_issue') and not selection.get('request_id') else call('get_recent_requests', **args)
                if logs.get('matched') and len(logs.get('requests', [])) == 1:
                    record = logs['requests'][0]
                    parts.append(f"请求 #{record['id']} 的日志耗时为 {record['latency_ms']} 毫秒，这是该次请求的实际记录。")
                else:
                    parts.append(selection.get('time_issue') or '暂时无法唯一确定你说的这次请求；请补充请求编号，或发生时间及当时的时区。已有信息无需重复提供。')
                intents = ['unknown']
                knowledge_answer = True
            if "quota" in intents:
                subs = call("get_subscriptions").get("subscriptions", [])
                active = [s for s in subs if s["status"] == "active" and s["expires_at"] > now()]
                if active:
                    for s in active:
                        parts.append(f"你的「{s['name']}」当前周期额度为 {money(s['quota_units'])}，已用 {money(s['used_units'])}，剩余 {money(s['remaining_units'])}。下一次刷新时间为 {s['reset_at'][:10]}（UTC），套餐到期时间为 {s['expires_at'][:10]}（UTC）。")
                        if not s["remaining_units"]:
                            parts.append("本周期额度已经用完；套餐仍有效不代表当前周期还有可用额度。可以等待下次刷新，或请人工协助调整套餐。")
                else:
                    parts.append("没有查到仍有效的套餐记录，需要核对购买订单。")
                if re.search(r'余额|兜底|扣款|继续|扣费', focus['message']):
                    keys = call('get_api_keys').get('keys', [])
                    for key in keys:
                        enabled = bool(key['balance_fallback'])
                        parts.append(f"本次查询：Key「{key['name']}」（末四位 {key['suffix']}）的余额兜底{'开启' if enabled else '关闭'}。" +
                                     ("使用该 Key 时，额度用尽可按演示规则使用可用余额。" if enabled else "使用该 Key 时，额度用尽不会自动扣账户余额继续请求。"))
                if re.search(r'提前.{0,6}(?:刷新|重置)|(?:刷新|重置).{0,6}提前', focus['message']):
                    parts.append('当前没有提前刷新周期的自动操作；是否调整套餐需管理员核验。')
            if "balance" in intents:
                account = call("get_account_overview")
                if "balance_units" in account:
                    balance = account["balance_units"]
                    parts.append(f"查询到你当前的账户余额是 {money(balance)}。")
                    eligibility = {}
                    wants_correction = re.search(r'回正|抹零|清除欠款|(?:帮我|请).{0,6}(?:处理|消除).{0,6}(?:负余额|欠费)', focus['message'])
                    if balance < 0 and wants_correction and not re.search(r"只查|仅查询|只看|不要操作|不需要操作", query):
                        eligibility = call("check_balance_adjustment")
                        if eligibility.get("eligible"):
                            declined = re.search(r'(?:先|暂时)?(?:不要|不用|不需要|别|不想).{0,8}(?:回正|调整余额)|(?:回正|调整余额).{0,8}(?:先不|不要|不用|暂停)', query)
                            if declined:
                                parts.append('这笔负余额符合演示回正条件；按你的要求暂不申请或执行回正，仅说明查询结果。')
                            else:
                                parts.append("正在按已核验的账本处理余额回正；处理结果以账户页面为准。")
                                actions.append({"type": "balance_fix", "expected_balance_units": balance, "expected_ledger_id": eligibility["ledger_id"], "reason": eligibility["reason"]})
                        else:
                            parts.append("当前不符合回正条件，原因是" + eligibility.get("reason", "缺少核验依据") + "。这部分需要人工核账。")
                            handoffs.append("核对负余额来源与回正条件")
                    if re.search(r'兜底|关闭.{0,8}(?:余额|扣费)|余额.{0,8}(?:关闭|没开|没有开启)', focus['message']):
                        keys = call('get_api_keys').get('keys', [])
                        for key in keys:
                            parts.append(f"本次查询：Key「{key['name']}」（末四位 {key['suffix']}）余额兜底{'开启' if key['balance_fallback'] else '关闭'}。")
                        if balance < 0 and eligibility.get('eligible'):
                            parts.append('账本核验显示这笔欠费来自最后一笔套餐超额请求；兜底关闭不代表此前请求结算时绝不会出现超额。不能由负余额反推 Key 开启了余额兜底。')
            if "technical" in intents:
                reported = re.findall(r"(?:HTTP|报错|错误|状态码|返回)\s*([45]\d{2})\b|\b([45]\d{2})\s*(?:错误|报错)", query, re.I)
                codes = sorted({code for pair in reported for code in pair if code})
                if codes:
                    parts.append("你反馈的错误码是 " + "、".join("HTTP " + code for code in codes) + "。")
                query_args = {k: v for k, v in selection.items() if k in QUERY_KEYS and v is not None}
                # An unresolved wall-clock time must not silently become a recent-log match.
                unresolved_time = selection.get('time_issue') and not selection.get('request_id')
                logs = {} if unresolved_time else call("get_recent_requests", **query_args)
                status = call("check_platform_status").get("channels", [])
                exact = bool(logs.get('matched'))
                if unresolved_time:
                    if re.search(r'信息.{0,6}发过|已经.{0,6}提供|没有请求编号|无法提供|没法复制', query):
                        parts.append('已收到时间和报错，也了解到你没有请求编号或无法继续补充；尚缺的日期或时区交由人工结合已有信息核验，无需重复提供。')
                        handoffs.append('请求时间仍有歧义，客户已提供现有信息，人工继续核查')
                    else:
                        parts.append(selection['time_issue'])
                elif logs.get('specific'):
                    if logs.get('conflicts'):
                        r = logs['requests'][0]
                        labels = {'model': '模型', 'status_code': '错误码', 'error': '错误文字', 'time': '发生时间'}
                        parts.append(f"查到当前账户的请求 #{r['id']}，但你提供的" + '、'.join(labels[c['field']] for c in logs['conflicts']) + '与记录不一致，请确认是否指这条请求，暂不认定为同一次故障。')
                    elif logs.get('ambiguous'):
                        parts.append('该时间范围内有多条匹配请求：' + '；'.join(f"#{r['id']} · {r['model']} · {r['display_time']['local']}" for r in logs['requests'][:5]) + '。请确认请求编号，暂不把合计费用当作某一条的扣费。')
                    elif not logs.get('count'):
                        parts.append('当前账户没有查到符合该编号或时间条件的请求，不能确认这次请求的扣费。请核对请求编号或已提供的时间信息。')
                    if logs.get('count') == 1:
                        r = logs['requests'][0]
                        t = r['display_time']
                        parts.append(f"请求 #{r['id']}：{r['model']}，HTTP {r['status_code']}，错误信息「{r['error'] or '无'}」。发生于 {t['local']}（{t['time_zone']}），对应 UTC {t['utc']}。")
                        if exact:
                            origin = {'subscription': '套餐额度', 'balance': '账户余额', 'none': '未计费', 'legacy': '历史记录，扣费来源未标记'}[r['billing_source']]
                            parts.append(f"这条请求的记录费用为 {money(r['cost_units'])}，来源：{origin}。" + ('已核实这条失败请求未扣费。' if r['status_code'] >= 400 and r['cost_units'] == 0 else ''))
                        if logs.get('conflicts'):
                            handoffs.append('请求编号与客户描述冲突，需确认目标请求')
                elif logs.get('count'):
                    failed = logs['failed_count']
                    parts.append(f"查询了最近 24 小时的 {logs['count']} 条请求记录，其中 {failed} 条失败。")
                    if failed:
                        parts.append('这些失败记录的扣费合计为 ' + money(logs['failed_cost_units']) + '，尚未定位你反馈的具体请求，不能将合计视为该次扣费。')
                    else:
                        parts.append('已查询记录均成功，但这不能排除未匹配到的其他请求发生故障；客户端整个任务耗时也不等于单次请求耗时。')
                else:
                    parts.append('最近 24 小时没有查到请求记录，暂时不能确定请求是否到达平台。')
                affected = [c for c in status if c['status'] != 'operational' and any(r['channel'] == c['name'] for r in logs.get('requests', []))]
                if affected:
                    parts.append('相关渠道当前存在异常，暂未公布恢复时间；当前状态不证明此前该请求的故障原因。')
                if re.search(r"401|403|鉴权", query):
                    keys = call("get_api_keys").get("keys", [])
                    if keys:
                        parts.append(f"当前可核对的 Key 为「{keys[0]['name']}」（末四位 {keys[0]['suffix']}）。请确认客户端使用的是同一 Key、线路和 Base URL；不要发送完整密钥。")
                    if "403" in query:
                        account = call("get_account_overview")
                        subs = call("get_subscriptions").get("subscriptions", [])
                        if account.get("balance_units", 0) < 0:
                            parts.append(f"账户存在 {money(account['balance_units'])} 的负余额，演示请求会被拦截。可以继续提出余额核验申请，由客服检查是否符合回正条件。")
                        elif not any(s["remaining_units"] > 0 for s in subs):
                            parts.append("账户当前没有可用的套餐额度；有效套餐的本周期额度已经用尽，或套餐已失效。")
                            if keys and not keys[0]["balance_fallback"]:
                                parts.append("查询到该 Key 的余额兜底关闭，因此账户有余额也不会自动抵扣。可以等待额度刷新或请管理员调整演示套餐。")
                if re.search(r"还是|仍然|试过|依然|照做|没变化|没改善|依旧", query):
                    parts.append("你已反馈尝试后仍未解决，这次不重复原建议，交由人工继续排查。")
                    handoffs.append("用户尝试后仍未解决，需要继续定位")
                if not exact and not logs.get('specific') and not unresolved_time:
                    parts.append(technical_followup(query, conversation))
                if re.search(r'无法提供|没法复制|无法复制|看不清|没有更多信息', query):
                    handoffs.append('客户无法补充更多错误信息，结合已有上下文继续人工排查')
                    parts.append('已保留你提供的信息，这部分转交人工继续核查，无需重复提交同样内容。')
            if "status" in intents:
                snapshot = call("check_platform_status")
                status = snapshot.get('channels', [])
                if status:
                    parts.append(f"本次查询时间：{snapshot['queried_at']}（UTC）。当前本地渠道状态：" + "；".join(f"{c['name']}：{'正常' if c['status']=='operational' else '异常'}（记录更新于 {c['updated_at']}）" for c in status) + "。当前状态不能用来确认此前某次请求的状态；未记录恢复时间时不承诺恢复日期。")
            if "configuration" in intents:
                setup = self.db.one("SELECT id,title,content FROM knowledge WHERE id='SETUP-001' AND published=1 AND review_after>=?", (now()[:10],))
                if setup:
                    supplied = '\n'.join([query] + [m['content'] for m in conversation['conversation'] if m['speaker'] in {'customer', 'human'}])
                    restarted = bool(re.search(r'(?:已|已经|重启过|重开过|试过).{0,15}(?:重启|重开)|(?:重启|重开).{0,8}(?:过|了|试过)', supplied))
                    guidance = setup['content']
                    if restarted:
                        guidance = '。'.join(part for part in guidance.split('。') if '重启' not in part)
                        guidance += '。已收到完成保存和重启的说明，无需重复此步骤；下一步核对最小请求的实际结果。'
                    parts.append(guidance)
                    if not any(e["id"] == setup["id"] for e in evidence):
                        evidence.append({"id": setup["id"], "title": setup["title"]})
                else:
                    parts.append("当前没有已发布且有效的接入文档，请补充客户端和目标接口以便人工核验。")
                if re.search(r'custom|自定义', focus['message'], re.I):
                    parts.append('客户端显示 Custom 或自定义，只是界面标签，不能单独证明请求已接通或实际使用了目标模型；需要实际请求结果来验证。')
                if re.search(r'已经|已|试过|重开过|重启过', query) and re.search(r'重启|重开|退出', query):
                    parts.append('已收到你保存配置并重开客户端的说明，无需重复此步骤；下一步应验证实际请求结果，不索要完整 Key。')
            if "refund" in intents:
                orders = call("get_orders").get("orders", [])
                history = call("get_user_ticket_history").get("tickets", [])
                requesting = bool(re.search(r"钱想退|帮我.{0,8}退(?!出)|我要.{0,8}退(?!出)|我想.{0,8}退(?!出)|想申请.{0,8}退(?!出)|申请退(?!出)|改为.{0,8}退(?!出)|退一下|全退(?!出)", focus['message'])) and not bool(re.search(r"怎么申请|如何申请|不(?:想|要)退款|取消退款", query))
                policy_only = bool(re.search(r"退款政策|退款规则|退款条件|怎么申请退款|如何申请退款|手续费", query)) and not requesting and "refund" not in context.get("active_intents", context.get("intents", []))
                if policy_only:
                    parts.append("你可以直接在当前工单提出退款申请，客服会核对订单并交由人工处理。退款结果、金额和到账日期以实际核验为准。")
                else:
                    if orders:
                        o = orders[0]
                        state = {"pending": "待处理", "approved": "人工已确认演示退款", "rejected": "未通过", "none": "尚无退款处理记录"}.get(o["refund_status"], o["refund_status"])
                        parts.append(f"查到订单 {o['number']}（{o['item']}，实付 ¥{o['amount_cents']/100:.2f}），退款状态为「{state}」。")
                        if o["refund_status"] == "none" and requesting:
                            actions.append({"type": "refund_request", "order_number": o["number"]})
                    else:
                        parts.append("目前没有查到可核对的订单，请补充订单号。")
                    parts.append("本工单已收到你的退款诉求，无需重复提交；这部分交由人工核验。不能承诺退款金额、结果或到账时间。")
                    handoffs.append("核验退款申请与订单状态")
                    if any(t["status"] == "waiting_human" for t in history):
                        parts.append("你已有其他等待人工的工单，本次会结合已有记录处理。")
                if re.search(r"手续费|部分|花掉|用过|消费|剩余全部|全退", query):
                    parts.append("部分或剩余余额退款、已消费部分的处理及手续费都需要人工核验；当前没有可确认的费率，不把账户余额或订单实付金额当作批准的退款金额。")
            if "invoice" in intents:
                invoices = call("get_invoices").get("invoices", [])
                if re.search(r"修改|重开|抬头.{0,6}(?:错|改)", query):
                    call("get_orders")
                if invoices:
                    i = invoices[0]
                    state = {"pending": "待开具", "issued": "已开具", "cancelled": "已取消"}.get(i["status"], i["status"])
                    parts.append(f"查询到发票抬头「{i['title']}」，金额 ¥{i['amount_cents']/100:.2f}，当前状态为「{state}」。")
                else:
                    parts.append("当前账号没有查到发票记录，请提供需要开票的订单号。")
                checking_result = bool(re.search(r'(?:改|处理|重开)(?:好|完|过|成功)?了吗|(?:改|处理|重开)好了(?:吗|没)|现在.{0,8}(?:抬头|状态)|已经.{0,8}(?:改|重开)', query))
                if checking_result and invoices and i.get('updated_at'):
                    parts.append(f"该发票记录已于 {i['updated_at']}（UTC）更新，以上是本次查询到的最新抬头与状态；没有邮件发送记录，不表示已发送邮件。")
                elif re.search(r"改|重开|不对|错误|差|核对|人工", query) or not invoices:
                    handoffs.append("人工核验开票信息与订单")
                    parts.append("开票信息修改或争议需要人工核验，这部分已列入待处理事项。")
            if "account" in intents:
                call("get_account_overview")
                handoffs.append("人工核验账号或接管诉求")
                parts.append("账号修改或人工接管请求需要客服核验，我不会直接重置密码或修改账号。请不要提供密码或完整 API Key。")
            # Only administrator-authored FAQ entries can directly answer an unknown
            # intent. Operational policy documents remain evidence, not executables.
            if not parts and intents == ["unknown"] and not focus['ambiguous']:
                faqs = [d for d in docs if "faq" in d["categories"] and d["query_term_coverage"] >= .55]
                if faqs:
                    parts.append(faqs[0]["text"])
                    knowledge_answer = True
            if not parts:
                if focus['ambiguous']:
                    names = list(dict.fromkeys(INTENT_LABELS[i] for group in focus['known_topics'] for i in group if i in INTENT_LABELS))
                    parts.append('本工单讨论过' + '、'.join(names) + '。你说的是其中哪一个问题？确认后再查询对应的当前状态，避免把不同事项混在一起。')
                elif focus['excluded_intents'] and not focus['message']:
                    parts.append('收到，按你的要求暂不处理这些事项。需要继续时，可以说明要回到哪个问题。')
                else:
                    clarification, escalate = clarify_missing(query, conversation)
                    parts.append(clarification)
                    if escalate:
                        handoffs.append('信息不足且客户无法继续补充，人工结合已有信息核查')

        if knowledge_answer and intents == ['unknown']:
            # Preserve the topic even when a static answer bypasses dynamic tools.
            # Otherwise the next short follow-up could inherit a paused old topic.
            topic_ids = {'PLAN-001': 'quota', 'BAL-001': 'balance', 'REFUND-001': 'refund',
                         'ERR-401': 'technical', 'ERR-503': 'technical', 'SETUP-001': 'configuration',
                         'INVOICE-001': 'invoice', 'STATUS-001': 'status', 'ACCOUNT-001': 'account'}
            intents = list(dict.fromkeys(topic_ids[e['id']] for e in evidence if e['id'] in topic_ids)) or (
                ['balance'] if scope['mode'] == 'account' else ['technical'] if scope['mode'] == 'duration' else ['unknown'])
        answerable = any(i in {"quota", "balance", "technical", "status", "configuration", "invoice"} for i in intents)
        route = "answer_and_handoff" if handoffs and answerable else "handoff" if handoffs else "clarify" if intents == ["unknown"] and not knowledge_answer else "answer"
        baseline = "\n\n".join(parts)
        answer = baseline
        original = baseline
        draft_check = None
        revision_attempted = False
        # Balance writes keep a fixed template reconciled at commit time.
        fixed_action = any(a["type"] == "balance_fix" for a in actions)
        if model and model_classified and not fixed_action:
            try:
                original = model.compose(query, tools.trace, baseline, context=conversation)
                candidate = original
                for attempt in range(2):
                    checked = quality_check(candidate, baseline, facts=tools.trace, context=conversation, query=query)
                    draft_check = checked
                    model_issues = model.review(candidate, baseline, context=conversation, facts=tools.trace, query=query)
                    if checked["passed"] and not model_issues:
                        break
                    if attempt == 0:
                        revision_attempted = True
                        feedback = [issue["message"] for issue in checked["issues"]]
                        feedback.extend((model.review_result or {}).get("issues", []) if isinstance(model, DeskModel) else model_issues)
                        candidate = model.compose(query, tools.trace, baseline, context=conversation,
                                                  previous_answer=scrub(candidate), revision_feedback=feedback)
                if checked["passed"] and not model_issues:
                    answer = candidate
                    provider = "openai"
                else:
                    model_fallback = True
                    provider = "local"
                    warnings.append("模型草稿未通过质检，已改用有查询依据的本地基准回复")
            except (GenerationError, KeyError, TypeError):
                model_fallback = True
                provider = "local"
                warnings.append("模型生成或质检不可用，已回退到有查询依据的本地回复")
        quality = quality_check(answer, baseline, facts=tools.trace, context=conversation, query=query)
        quality["warnings"] = warnings
        # A recovered model failure is informational. Missing business evidence
        # still blocks delivery, as do failed checks on the final answer itself.
        quality["blocking_warnings"] = blocking_warnings
        quality["model_fallback"] = model_fallback
        quality["revision_attempted"] = revision_attempted
        quality['topic'] = {'current_intents': intents, 'excluded_intents': focus['excluded_intents'],
                            'referenced_previous_topic': bool(focus['reference_question']),
                            'clarification_required': focus['ambiguous']}
        if draft_check is not None:
            quality["model_draft_check"] = draft_check
        if isinstance(model, DeskModel):
            quality["model"] = {**model.metadata(), "source": "model" if provider == "openai" else "policy" if fixed_action else "local",
                                "history_messages": len(conversation["conversation"]),
                                "history_truncated": conversation["history_truncated"],
                                "includes_human": any(m["speaker"] == "human" for m in conversation["conversation"])}
            if model_fallback and draft_check is not None:
                warnings.extend("规则质检：" + issue["message"] for issue in draft_check["issues"])
                warnings.extend("模型复核：" + issue for issue in (model.review_result or {}).get("issues", []))
            failures = [c["error"] for c in model.trace if c.get("error")]
            for failure in failures[-1:]:
                detail = failure["message"] + (f" HTTP {failure['http_status']}。" if failure.get("http_status") else "")
                warnings.append(detail)
        quality["revised"] = answer != original
        active_intents = [i for i in intents if i not in {"resolved", "resolution_check", "greeting", "unknown"}]
        if not active_intents and intents != ["resolved"] and scope['mode'] != 'missing' and not focus['explicit_switch']:
            active_intents = context.get("active_intents", context.get("intents", []))
        history = [] if intents == ['resolved'] else remember_topic(context, query, intents)
        request_focus = selection if 'technical' in intents else context.get('request_focus', {})
        context = {"request_focus": request_focus, "intents": intents, "active_intents": active_intents, "topic_history": history, "last_question": query[:500], "pending_handoffs": handoffs,
                   "attempted": bool(re.search(r"试过|还是|仍然|依然", query)), "updated_at": now()}
        return {"route": route, "intents": intents, "answer": answer, "original_answer": original,
                "baseline": baseline, "internal_note": "；".join(handoffs) or "根据当前工单所属用户的数据答复，无需额外转交。",
                "tools": tools.trace, "evidence": evidence, "quality": quality, "actions": actions,
                "model_evidence_summary": getattr(model, "evidence_summary", ""),
                "provider": provider, "context": context, "elapsed_ms": round((time.perf_counter()-started)*1000)}
