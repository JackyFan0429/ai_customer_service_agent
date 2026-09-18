#!/usr/bin/env python3
"""Create a conservative, auditable semantic layer over canonical support cases.

This first version intentionally uses deterministic rules and has no external API
dependency. It does not claim that historical support answers are correct. Instead,
it identifies candidate troubleshooting evidence, assigns a semantic quality tier,
and separates retrieval-eligible cases from cases requiring review.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "1.1.0"

PRODUCT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("clienta", ("clienta",)),
    ("clientb", ("clientb",)),
    ("model_a", ("modela", "模型a", "模型 a")),
    ("model_b", ("modelb", "模型b", "模型 b")),
    ("image_generation", ("生图", "绘图", "图生图", "image")),
)

CLIENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("clienta_cli", ("clienta cli",)),
    ("clienta_desktop", ("clienta desktop",)),
    ("clientb_code", ("clientb code", "clientbcode")),
    ("clientc", ("clientc",)),
    ("clientd", ("clientd",)),
    ("web_client", ("web client", "网页客户端")),
)

CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("refund", ("退款", "退订", "买错")),
    ("invoice", ("发票", "开票")),
    ("account_login", ("登录", "密码", "账号不可用", "账户不可用")),
    ("quota_balance", ("额度", "余额", "充值", "兑换码", "福利")),
    ("subscription_plan", ("套餐", "月卡", "周卡", "订阅", "plan")),
    ("billing_usage", ("账单", "扣费", "消耗", "倍率", "返利")),
    ("auth_permission", ("403", "forbidden", "unauthorized", "not authorized", "access point", "无权限")),
    ("request_limit", ("413", "请求过大", "rate limit", "限流", "429")),
    ("availability_network", ("service unavailable", "无法连接", "连接失败", "中断", "重连", "reconnecting", "熔断", "超时", "502", "500", "521", "服务器失联", "请求失败")),
    ("configuration_integration", ("配置", "接入", "接口", "endpoint", "base url", "api地址", "api 地址", "代理")),
    ("model_availability", ("模型广场", "模型不可用", "无法使用模型", "模型问题", "model not", "not found")),
    ("image_generation", ("生图", "绘图", "图生图", "图片编辑")),
)

ERROR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:http\s*)?[345]\d{2}\b", re.I),
    re.compile(r"\b(?:invalid_request_error|forbidden_error|service unavailable|unexpected error|rate limit(?:ed)?|reconnecting)\b", re.I),
    re.compile(r"current plan does not allow this access point", re.I),
    re.compile(r"stream disconnected(?: before completion)?", re.I),
    re.compile(r"error sending request", re.I),
)

ACTIONABLE_SUPPORT_RE = re.compile(
    r"(?:请|建议|可以|需要|尝试|检查|确认|核对|切换|更换|重新|重试|配置|设置|访问|"
    r"使用|更新|升级|下载|打开|关闭|删除|联系|提供|截图|退款|充值|恢复|修复|处理)",
    re.I,
)
RESOLUTION_RE = re.compile(
    r"(?:解决了|已经解决|已解决|恢复了|已恢复|可以用了|能用了|正常了|好了|成功了|没问题了)",
    re.I,
)
TIME_SENSITIVE_RE = re.compile(
    r"(?:服务波动|线路波动|系统故障|服务故障|临时故障|临时调整|宕机|炸了|维护中|"
    r"服务已恢复|已经恢复服务|下线|当前不可用|今天.{0,12}故障|刚刚.{0,12}故障)",
    re.I,
)
TEST_OR_JUNK_RE = re.compile(
    r"^(?:线上)?测试(?:工单)?$|^test(?: ticket)?$|^\d{1,12}$|^[?？!！]{1,8}$|<a\s+href|123123",
    re.I,
)
LOW_VALUE_SUPPORT_RE = re.compile(
    r"^\s*(?:/process|收到|好的|好|嗯|看看|稍等|等一下|已处理|处理中|正在处理中|"
    r"正在查看|已经反馈|已反馈|谢谢|不客气|ok|okay|test|\d+)[～~。！!]?\s*$",
    re.I,
)
REDACTION_TOKEN_RE = re.compile(
    r"<(?:EMAIL|API_KEY|TOKEN|SECRET|ID|USER_ID|SUBSCRIPTION_ID)>"
)
SECONDARY_SECRET_RE = re.compile(
    r"\b(?:nb|sk|rk|pk|key)[_-][A-Za-z0-9_-]{16,}\b",
    re.I,
)
JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_-]{10,})?\b"
)
LABELED_SECRET_RE = re.compile(
    r"(?i)\b(api[_ -]?key|token|secret|password)\s*[：:=]\s*([^\s,;]{8,})"
)
CONTENT_INJECTION_RE = re.compile(
    r"(?:<\s*script\b|javascript\s*:|on(?:error|load|click)\s*=|"
    r"忽略.{0,20}(?:之前|以上|系统).{0,20}(?:指令|提示词)|"
    r"ignore.{0,30}(?:previous|prior|system).{0,20}(?:instructions?|prompt)|"
    r"system\s+prompt|系统提示词)",
    re.I | re.S,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="canonical_cases.jsonl")
    parser.add_argument("--output", required=True, help="Output directory")
    return parser.parse_args()


def clean(value: Any) -> str:
    text = str(value or "")
    text = SECONDARY_SECRET_RE.sub("<API_KEY>", text)
    text = JWT_RE.sub("<TOKEN>", text)
    text = LABELED_SECRET_RE.sub(lambda match: f"{match.group(1)}：<SECRET>", text)
    return re.sub(r"\s+", " ", text).strip()


def normalized(value: Any) -> str:
    return clean(value).casefold()


def compact(value: Any, limit: int = 280) -> str:
    text = clean(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def unique(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def sanitize_value(value: Any) -> Any:
    """Apply the KB's second redaction pass to copied source fields."""
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_value(item) for key, item in value.items()}
    return value


def match_labels(text: str, rules: Iterable[tuple[str, tuple[str, ...]]]) -> list[str]:
    haystack = normalized(text)
    return [label for label, terms in rules if any(term.casefold() in haystack for term in terms)]


def primary_category(text: str) -> tuple[str, list[str]]:
    labels = match_labels(text, CATEGORY_RULES)
    return (labels[0] if labels else "other", labels)


def extract_error_signatures(text: str) -> list[str]:
    found: list[str] = []
    for pattern in ERROR_PATTERNS:
        for match in pattern.finditer(text):
            found.append(clean(match.group(0)))

    for raw_line in str(text).splitlines():
        line = clean(raw_line)
        if not line or len(line) > 220:
            continue
        if re.search(r"(?:error|exception|failed|失败|报错|错误)", line, re.I):
            found.append(compact(line, 180))
    return unique(found)[:12]


def meaningful_problem(case: dict[str, Any]) -> str:
    title = clean(case.get("title"))
    description = clean(case.get("description"))
    if title and not TEST_OR_JUNK_RE.search(title):
        if description and normalized(description) != normalized(title):
            return compact(f"{title}：{description}", 360)
        return compact(title, 360)
    if description and not TEST_OR_JUNK_RE.search(description):
        return compact(description, 360)
    first_user = next(
        (clean(m.get("content")) for m in case.get("messages", []) if m.get("role") == "user" and clean(m.get("content"))),
        "",
    )
    return compact(first_user, 360)


def candidate_solution_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for message in messages:
        content = clean(message.get("content"))
        if message.get("role") != "support" or len(content) < 6:
            continue
        if LOW_VALUE_SUPPORT_RE.match(content):
            continue
        if ACTIONABLE_SUPPORT_RE.search(content) or len(content) >= 45:
            candidates.append(
                {
                    "message_id": message.get("message_id"),
                    "text": compact(content, 360),
                    "status": "historical_candidate_not_verified",
                }
            )
    return candidates[:8]


def resolution_evidence(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for message in messages:
        content = clean(message.get("content"))
        if message.get("role") == "user" and RESOLUTION_RE.search(content):
            evidence.append(
                {
                    "message_id": message.get("message_id"),
                    "text": compact(content, 220),
                }
            )
    return evidence[:4]


def diagnostic_questions(category: str) -> list[str]:
    common = ["确认具体客户端、模型和请求入口", "提供可复现的错误文本与发生时间"]
    additions = {
        "availability_network": ["确认是否使用代理并对比其他网络线路", "确认问题是持续发生还是偶发"],
        "configuration_integration": ["提供已脱敏的客户端配置和 Base URL", "确认客户端版本及所用 API 协议"],
        "auth_permission": ["确认套餐、渠道和访问入口是否匹配", "提供已脱敏的鉴权错误响应"],
        "quota_balance": ["确认相关套餐、购买时间和额度刷新周期", "核对控制台余额与实际请求消耗"],
        "subscription_plan": ["确认套餐名称、购买时间和目标使用场景"],
        "billing_usage": ["提供账单时间范围和对应请求记录", "核对倍率、模型和渠道"],
        "refund": ["确认订单、购买时间、已使用情况和退款原因"],
        "invoice": ["确认订单主体、金额和开票信息"],
        "account_login": ["确认登录方式以及是否能够完成密码重置"],
        "request_limit": ["提供请求大小、并发量和完整状态码"],
        "model_availability": ["确认模型名称、渠道、套餐和调用入口"],
        "image_generation": ["确认输入图片规格、模型和请求参数"],
    }
    return unique(common + additions.get(category, []))


def quality_assessment(
    case: dict[str, Any],
    problem: str,
    errors: list[str],
    candidates: list[dict[str, Any]],
    resolutions: list[dict[str, Any]],
    combined_text: str,
) -> dict[str, Any]:
    messages = case.get("messages", [])
    users = [m for m in messages if m.get("role") == "user" and clean(m.get("content"))]
    support = [m for m in messages if m.get("role") == "support" and clean(m.get("content"))]
    warnings = set(case.get("warnings", []))

    flags: list[str] = []
    if not messages:
        flags.append("no_dialogue_messages")
    if not users:
        flags.append("missing_user_message")
    if not support:
        flags.append("missing_support_message")
    if "next_ticket_started_before_close" in warnings:
        flags.append("flattened_boundary_uncertain")
    junk_text = " ".join(filter(None, [clean(case.get("title")), clean(case.get("description"))]))
    if TEST_OR_JUNK_RE.search(junk_text) or (junk_text and len(junk_text) <= 3):
        flags.append("possible_test_or_junk")
    if len(problem) < 8 and not errors:
        flags.append("low_information_problem")
    if TIME_SENSITIVE_RE.search(combined_text):
        flags.append("time_sensitive_or_incident_content")
    if REDACTION_TOKEN_RE.search(combined_text):
        flags.append("contains_redaction_placeholders")
    if CONTENT_INJECTION_RE.search(combined_text):
        flags.append("content_injection_risk")

    score = 0
    score += 20 if len(problem) >= 8 else 5 if problem else 0
    score += 10 if errors else 0
    score += 15 if users else 0
    score += 15 if support else 0
    score += 15 if candidates else 0
    score += 15 if resolutions else 0
    score += 10 if case.get("canonical_source_type") == "original_forum" else 5
    score += 5 if case.get("status") == "closed" else 0
    score -= 35 if "possible_test_or_junk" in flags else 0
    score -= 30 if "no_dialogue_messages" in flags else 0
    score -= 15 if "missing_user_message" in flags else 0
    score -= 15 if "missing_support_message" in flags else 0
    score -= 10 if "flattened_boundary_uncertain" in flags else 0
    score = max(0, min(100, score))

    blocking = {
        "no_dialogue_messages",
        "missing_user_message",
        "missing_support_message",
        "possible_test_or_junk",
        "low_information_problem",
        "content_injection_risk",
    }
    if blocking.intersection(flags) or score < 45:
        tier = "archive_only"
    elif resolutions and candidates and score >= 80 and "flattened_boundary_uncertain" not in flags:
        tier = "verified_case"
    else:
        tier = "reference_case"

    review_reasons = [
        flag
        for flag in flags
        if flag
        in {
            "flattened_boundary_uncertain",
            "possible_test_or_junk",
            "time_sensitive_or_incident_content",
            "no_dialogue_messages",
            "missing_user_message",
            "missing_support_message",
            "low_information_problem",
            "content_injection_risk",
        }
    ]
    if tier == "archive_only" and not review_reasons:
        review_reasons.append("semantic_quality_below_threshold")

    if tier == "archive_only":
        retrieval_status = "excluded"
    elif review_reasons:
        retrieval_status = "review_required"
    else:
        retrieval_status = "eligible"

    return {
        "semantic_score": score,
        "semantic_tier": tier,
        "retrieval_status": retrieval_status,
        "requires_human_review": bool(review_reasons),
        "review_reasons": review_reasons,
        "quality_flags": flags,
        "historical_answer_status": "candidate_only_not_fact_checked",
        "official_conflict_status": "not_checked_no_official_kb",
    }


def enrich_case(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    messages = case.get("messages", [])
    all_content = "\n".join(clean(m.get("content")) for m in messages)
    user_content = "\n".join(
        clean(m.get("content")) for m in messages if m.get("role") == "user"
    )
    issue_content = "\n".join(
        filter(None, [clean(case.get("title")), clean(case.get("description")), user_content])
    )
    combined = "\n".join(
        filter(None, [clean(case.get("title")), clean(case.get("description")), all_content])
    )
    problem = meaningful_problem(case)
    errors = extract_error_signatures(issue_content)
    # Classify the user's issue from the title, description and user-authored text.
    # Support replies may mention refund, quota or another fallback path that does
    # not represent the user's original intent.
    products = match_labels(issue_content, PRODUCT_RULES)
    clients = match_labels(issue_content, CLIENT_RULES)
    category, category_tags = primary_category(issue_content)
    candidates = candidate_solution_messages(messages)
    resolutions = resolution_evidence(messages)

    if resolutions:
        resolution_status = "user_confirmed_resolved"
        resolution_confidence = 0.90
    elif case.get("status") == "closed" and candidates:
        resolution_status = "closed_without_user_confirmation"
        resolution_confidence = 0.45
    elif case.get("status") == "closed":
        resolution_status = "closed_no_solution_evidence"
        resolution_confidence = 0.25
    else:
        resolution_status = "unknown_or_unresolved"
        resolution_confidence = 0.15

    quality = quality_assessment(case, problem, errors, candidates, resolutions, combined)
    evidence = {
        "user_message_ids": [m.get("message_id") for m in messages if m.get("role") == "user"],
        "support_message_ids": [m.get("message_id") for m in messages if m.get("role") == "support"],
        "candidate_solution_message_ids": [x["message_id"] for x in candidates],
        "resolution_message_ids": [x["message_id"] for x in resolutions],
    }
    summary_parts = [problem]
    if errors:
        summary_parts.append("错误特征：" + "；".join(errors[:4]))
    if candidates:
        summary_parts.append("历史客服候选处理：" + candidates[0]["text"])
    case_summary = compact("。".join(x.rstrip("。") for x in summary_parts if x), 700)

    enrichment = {
        "schema_version": SCHEMA_VERSION,
        "ticket_id": str(case.get("ticket_id", "")),
        "products": products or ["unknown"],
        "clients": clients,
        "primary_category": category,
        "category_tags": category_tags,
        "problem_summary": problem,
        "symptoms": [problem] if problem else [],
        "error_signatures": errors,
        "recommended_diagnostic_questions": diagnostic_questions(category),
        "historical_solution_candidates": candidates,
        "resolution": {
            "status": resolution_status,
            "confidence": resolution_confidence,
            "evidence": resolutions,
        },
        "quality": quality,
        "case_summary": case_summary,
        "evidence": evidence,
        "provenance": {
            "canonical_source": case.get("canonical_source"),
            "canonical_source_type": case.get("canonical_source_type"),
            "structure_confidence": case.get("structure_confidence"),
            "source_case_quality": case.get("case_quality"),
        },
    }
    enriched = sanitize_value(case)
    enriched["enrichment"] = enrichment
    return enriched, enrichment


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSON on line {number}: {exc}") from exc
            if not isinstance(row, dict) or "ticket_id" not in row:
                raise SystemExit(f"Invalid case record on line {number}")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"Input does not exist: {input_path}")
    output_dir.mkdir(parents=True, exist_ok=True)

    source_rows = read_jsonl(input_path)
    enriched_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    low_confidence: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []

    for case in source_rows:
        enriched, semantic = enrich_case(case)
        enriched_rows.append(enriched)
        quality = semantic["quality"]
        if quality["retrieval_status"] == "eligible":
            summaries.append(semantic)
        if quality["semantic_tier"] == "archive_only":
            low_confidence.append(enriched)
        if quality["requires_human_review"]:
            review_rows.append(
                {
                    "ticket_id": semantic["ticket_id"],
                    "review_reasons": quality["review_reasons"],
                    "semantic_tier": quality["semantic_tier"],
                    "retrieval_status": quality["retrieval_status"],
                    "case_summary": semantic["case_summary"],
                    "official_conflict_status": quality["official_conflict_status"],
                    "provenance": semantic["provenance"],
                }
            )

    counts = {
        "semantic_tiers": Counter(x["enrichment"]["quality"]["semantic_tier"] for x in enriched_rows),
        "retrieval_statuses": Counter(x["enrichment"]["quality"]["retrieval_status"] for x in enriched_rows),
        "primary_categories": Counter(x["enrichment"]["primary_category"] for x in enriched_rows),
        "products": Counter(p for x in enriched_rows for p in x["enrichment"]["products"]),
        "quality_flags": Counter(f for x in enriched_rows for f in x["enrichment"]["quality"]["quality_flags"]),
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "input": str(input_path),
        "input_case_count": len(source_rows),
        "output_counts": {
            "canonical_cases_enriched": len(enriched_rows),
            "case_summaries_retrieval_eligible": len(summaries),
            "low_confidence_cases": len(low_confidence),
            "conflicts_or_review": len(review_rows),
        },
        **{key: dict(value.most_common()) for key, value in counts.items()},
        "important_limitations": [
            "This deterministic baseline classifies text by explicit patterns; it is not a fact checker.",
            "Historical solution candidates have not been checked against an official knowledge base.",
            "A closed ticket is not treated as proof that the issue was resolved.",
            "Only user-authored confirmation phrases can produce user_confirmed_resolved.",
            "case_summaries.jsonl contains only retrieval-eligible records; review-required and archive-only records are excluded.",
        ],
    }

    write_jsonl(output_dir / "canonical_cases_enriched.jsonl", enriched_rows)
    write_jsonl(output_dir / "case_summaries.jsonl", summaries)
    write_jsonl(output_dir / "low_confidence_cases.jsonl", low_confidence)
    write_jsonl(output_dir / "conflicts_or_review.jsonl", review_rows)
    (output_dir / "enrichment_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(report["output_counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
