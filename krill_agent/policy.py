"""Evidence eligibility and customer-routing policy."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from .models import Evidence, PolicyDecision, Route


ACCOUNT_SPECIFIC_RE = re.compile(
    r"(我的|我这|帮我|替我).{0,10}(账号|账户|订单|余额|额度|套餐|订阅|退款|发票|邮箱|登录)"
    r"|(订单号|支付截图|退款|重复扣费|余额异常|账号被封|账户被封)",
    re.I,
)
LIVE_STATE_RE = re.compile(r"(现在|今天|刚刚|此刻).{0,12}(挂了|故障|宕机|异常|不可用|恢复|状态)", re.I)
VAGUE_RE = re.compile(r"^(不能用|用不了|不行|报错了|有问题|怎么办|help|你好)[!！?？。\s]*$", re.I)
IDENTITY_RE = re.compile(
    r"^(你是谁|你是什么|你是机器人吗|who are you|what are you)[!！?？。\s]*$",
    re.I,
)
GREETING_RE = re.compile(r"^(你好|您好|hello|hi|hey)[!！?？。\s]*$", re.I)

IDENTITY_RESPONSE = "我是 Krill AI 客服助手，可以协助解答产品使用、订单和常见问题。请问有什么可以帮您？"
GREETING_RESPONSE = "您好，我是 Krill AI 客服助手。请问有什么可以帮您？"


def is_current(record: dict[str, Any], today: date) -> bool:
    if record.get("precedence") != "P1":
        return True
    review_after = record.get("review_after")
    if not review_after:
        return False
    try:
        return date.fromisoformat(str(review_after)) >= today
    except ValueError:
        return False


def select_evidence(
    records: list[dict[str, Any]],
    *,
    today: date,
    min_score: float,
    query: str | None = None,
) -> tuple[list[Evidence], list[Evidence]]:
    customer: list[Evidence] = []
    internal: list[Evidence] = []
    for record in records:
        if float(record.get("score", 0.0)) < min_score:
            continue
        if query is not None:
            coverage = float(record.get("query_term_coverage", 0.0))
            query_term_count = int(record.get("query_term_count", 0))
            required_coverage = 0.5 if query_term_count <= 2 else 0.4
            if query_term_count == 0 or coverage < required_coverage:
                continue
            critical_terms = set(record.get("critical_query_terms", []))
            matched_critical_terms = set(record.get("matched_critical_terms", []))
            if critical_terms and not critical_terms.issubset(matched_critical_terms):
                continue
        current = is_current(record, today)
        evidence = Evidence.from_record(record, current=current)
        if evidence.audience == "restricted_internal":
            continue
        if evidence.audience == "agent_internal":
            internal.append(evidence)
            continue
        if evidence.precedence == "P1" and not current:
            continue
        if evidence.precedence == "P2" and evidence.conflict_status != "no_rule_conflict_detected":
            continue
        customer.append(evidence)
    if customer:
        relative_floor = max(min_score, customer[0].score * 0.65)
        customer = [item for item in customer if item.score >= relative_floor][:5]
    return customer, internal[:5]


def decide_route(query: str, customer: list[Evidence], internal: list[Evidence]) -> PolicyDecision:
    normalized = query.strip()
    internal_ids = tuple(item.document_id for item in internal)
    if IDENTITY_RE.fullmatch(normalized):
        return PolicyDecision(
            route=Route.ANSWER,
            reason="标准身份说明，不需要检索知识库",
            customer_message=IDENTITY_RESPONSE,
        )
    if GREETING_RE.fullmatch(normalized):
        return PolicyDecision(
            route=Route.ANSWER,
            reason="标准问候，不需要检索知识库",
            customer_message=GREETING_RESPONSE,
        )
    if ACCOUNT_SPECIFIC_RE.search(normalized):
        return PolicyDecision(
            route=Route.ESCALATE,
            reason="需要查询或修改客户账户、订单或财务状态",
            customer_message="这个问题涉及你的账户或订单状态，需要人工客服核验。请准备账号 ID、相关订单号和必要的错误截图；不要发送密码、API Key 或完整支付凭证。",
            internal_document_ids=internal_ids,
        )
    if LIVE_STATE_RE.search(normalized):
        return PolicyDecision(
            route=Route.ESCALATE,
            reason="需要实时服务状态，静态知识库无法确认",
            customer_message="这个问题需要查询实时服务状态，我目前只有静态知识库，无法可靠确认。请转人工客服或查看官方状态通知，并提供发生时间、客户端和完整报错。",
            internal_document_ids=internal_ids,
        )
    if len(normalized) < 4 or VAGUE_RE.fullmatch(normalized):
        return PolicyDecision(
            route=Route.CLARIFY,
            reason="问题信息不足",
            customer_message="请补充你使用的产品或客户端、操作步骤，以及完整报错文字（请先遮盖 API Key、密码和个人信息）。",
            internal_document_ids=internal_ids,
        )
    if not customer:
        return PolicyDecision(
            route=Route.CLARIFY,
            reason="知识库没有足够相关且可公开的证据支持回答",
            customer_message="我暂时没有从知识库中找到足够可靠的答案。请再详细说明你使用的产品或客户端、想完成的操作、已经尝试的步骤，以及完整报错文字（请先遮盖 API Key、密码和个人信息）。",
            internal_document_ids=internal_ids,
        )
    return PolicyDecision(
        route=Route.ANSWER,
        reason="存在符合时效和披露规则的证据",
        internal_document_ids=internal_ids,
    )
