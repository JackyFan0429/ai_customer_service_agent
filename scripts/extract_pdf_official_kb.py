#!/usr/bin/env python3
"""Extract active, source-attributed official KB chunks from the internal PDF.

The PDF uses visual strike-through rectangles. Any text line intersected by a
strike-through is written only to an audit file and is never emitted as active
knowledge. Restricted payment/internal-pricing sections are retained in the
normalized source output with retrieval_policy=excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

import pdfplumber


SECTION_RE = re.compile(r"^(\d+\.\d+\.\d+)\s+(.+)$")
CONTAINER_HEADING_RE = re.compile(r"^\d+(?:\.\d+)?\s+\S")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]", re.UNICODE)
HIGH_VOLATILITY_RE = re.compile(
    r"(?:目前|当前|现在|最新|价格|倍率|额度|套餐|模型|退款|发票|并发|RPM|QPM|"
    r"支持|上线|下线|活动|返利|每天|每日|每周|限额)",
    re.I,
)
INTERNAL_RE = re.compile(
    r"(?:内部说明|原因判断（内部）|内部口径|提交.{0,8}(?:管理员|技术组|财务)|后台|号池|白名单)",
    re.I,
)
RESTRICTED_SECTION_IDS = {"2.2.7", "4.1.3", "5.1.5"}
RESTRICTED_RE = re.compile(
    r"(?:USDT|BSC20|TRC20|收款地址|内部报价|预存\s*\d+|全局限制为总计)",
    re.I,
)

PRODUCT_RULES = {
    "codex": ("codex", "gpt-5", "responses"),
    "claude": ("claude", "anthropic", "opus", "sonnet"),
    "openai_gpt": ("openai", "gpt", "chat completions"),
    "deepseek": ("deepseek",),
    "gemini": ("gemini",),
    "grok": ("grok",),
    "image_generation": ("生图", "图片", "image-2", "gpt-image"),
}

CLIENT_RULES = {
    "codex_cli": ("codex cli",),
    "codex_desktop": ("codex desktop", "codex app"),
    "claude_code": ("claude code",),
    "cherry_studio": ("cherry studio",),
    "openclaw": ("openclaw",),
    "opencode": ("opencode",),
    "newapi": ("newapi",),
    "cc_switch": ("cc-switch",),
}

CATEGORY_RULES = {
    "refund": ("退款",),
    "invoice": ("发票", "开票"),
    "account_login": ("登录", "账号", "密码"),
    "quota_balance": ("余额", "额度", "返利"),
    "subscription_plan": ("套餐", "月卡", "周卡", "天卡"),
    "billing_usage": ("计费", "扣费", "倍率", "credit", "token"),
    "auth_permission": ("403", "鉴权", "invalid key", "api key"),
    "request_limit": ("429", "503", "限流", "并发", "rpm", "qpm", "413"),
    "availability_network": ("网络", "cloudflare", "cdn", "stream disconnected", "502", "522", "524", "reconnecting"),
    "configuration_integration": ("配置", "接入", "base_url", "base url", "协议", "responses"),
    "model_availability": ("模型", "model", "上下文"),
    "image_generation": ("生图", "图片", "image-2"),
    "risk_control": ("风控", "cyber", "policy", "安全策略"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Official source PDF")
    parser.add_argument("--output", required=True, help="Official JSONL output")
    parser.add_argument("--audit", required=True, help="Outdated/restricted audit JSON")
    parser.add_argument("--report", required=True, help="Extraction report JSON")
    return parser.parse_args()


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = CONTROL_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def strike_rectangles(page: Any) -> list[dict[str, Any]]:
    strikes: list[dict[str, Any]] = []
    for rect in page.rects:
        width = float(rect["x1"] - rect["x0"])
        height = float(rect["bottom"] - rect["top"])
        # Full-width rectangles are section dividers, not strike-throughs.
        if 10 < width < 530 and height < 2:
            strikes.append(rect)
    return strikes


def line_is_struck(line: dict[str, Any], strikes: list[dict[str, Any]]) -> bool:
    chars = line.get("chars", [])
    if not chars:
        return False
    x0 = min(float(char["x0"]) for char in chars)
    x1 = max(float(char["x1"]) for char in chars)
    top = min(float(char["top"]) for char in chars)
    bottom = max(float(char["bottom"]) for char in chars)
    for rect in strikes:
        y = (float(rect["top"]) + float(rect["bottom"])) / 2
        overlap = min(x1, float(rect["x1"])) - max(x0, float(rect["x0"]))
        if top <= y <= bottom and overlap > 8:
            return True
    return False


def labels(text: str, rules: dict[str, tuple[str, ...]]) -> list[str]:
    haystack = text.casefold()
    return [name for name, terms in rules.items() if any(term.casefold() in haystack for term in terms)]


def keywords(text: str) -> list[str]:
    values = re.findall(
        r"\b(?:HTTP\s*)?[1-5]\d{2}\b|[A-Za-z][A-Za-z0-9_.+/-]{2,}|[\u4e00-\u9fff]{2,8}",
        text,
        re.I,
    )
    counts = Counter(value.casefold() for value in values)
    return [value for value, _ in counts.most_common(24)]


def classify_policy(section_id: str, text: str) -> tuple[str, str]:
    if section_id in RESTRICTED_SECTION_IDS or RESTRICTED_RE.search(text):
        return "restricted_internal", "excluded"
    if INTERNAL_RE.search(text):
        return "agent_internal", "include_with_non_disclosure"
    return "customer_safe", "include"


def extract(pdf_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    source_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    active_lines: list[dict[str, Any]] = []
    outdated_lines: list[dict[str, Any]] = []

    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, 1):
            strikes = strike_rectangles(page)
            for line in page.extract_text_lines(layout=False, return_chars=True):
                text = normalize(line.get("text", ""))
                if not text:
                    continue
                record = {
                    "page": page_number,
                    "text": text,
                    "top": round(float(line["top"]), 2),
                }
                if line_is_struck(line, strikes):
                    record["reason"] = "visual_strikethrough_outdated"
                    outdated_lines.append(record)
                else:
                    active_lines.append(record)

    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in active_lines:
        match = SECTION_RE.match(line["text"])
        if match:
            if current:
                sections.append(current)
            current = {
                "section_id": match.group(1),
                "title": match.group(2).strip(),
                "pages": [line["page"]],
                "body_lines": [],
            }
            continue
        if CONTAINER_HEADING_RE.match(line["text"]):
            # Main chapter/subchapter headings are metadata, not body content
            # for the preceding leaf section.
            continue
        if current:
            current["body_lines"].append(line["text"])
            if line["page"] not in current["pages"]:
                current["pages"].append(line["page"])
    if current:
        sections.append(current)

    rows: list[dict[str, Any]] = []
    section_occurrences: Counter[str] = Counter()
    for section in sections:
        content = normalize("\n".join(section["body_lines"]))
        if not content:
            continue
        full_text = f"{section['title']}\n{content}"
        audience, retrieval_policy = classify_policy(section["section_id"], full_text)
        volatility = "high" if HIGH_VOLATILITY_RE.search(full_text) else "medium"
        review_after = "2026-09-08" if volatility == "high" else "2026-10-01"
        section_occurrences[section["section_id"]] += 1
        occurrence = section_occurrences[section["section_id"]]
        occurrence_suffix = "" if occurrence == 1 else f"-part-{occurrence}"
        rows.append(
            {
                "doc_id": (
                    f"krill-internal-{section['section_id'].replace('.', '-')}"
                    f"{occurrence_suffix}-2026-09-01"
                ),
                "section_id": section["section_id"],
                "section_occurrence": occurrence,
                "title": section["title"],
                "content": content,
                "authority": "official_internal_document",
                "source_url": f"internal://krillai_ticket_knowledge_base.pdf#pages={min(section['pages'])}-{max(section['pages'])}",
                "source_document": pdf_path.name,
                "source_sha256": source_hash,
                "retrieved_at": "2026-09-01",
                "last_verified_in_document": "2026-07-17",
                "review_after": review_after,
                "volatility": volatility,
                "audience": audience,
                "retrieval_policy": retrieval_policy,
                "products": labels(full_text, PRODUCT_RULES),
                "clients": labels(full_text, CLIENT_RULES),
                "categories": labels(full_text, CATEGORY_RULES) or ["other"],
                "keywords": keywords(full_text),
                "claims": [],
                "outdated_content_policy": "visual_strikethrough_removed_before_chunking",
            }
        )

    audit = {
        "source_document": pdf_path.name,
        "source_sha256": source_hash,
        "outdated_line_count": len(outdated_lines),
        "outdated_pages": sorted({line["page"] for line in outdated_lines}),
        "outdated_lines": outdated_lines,
        "restricted_sections": [
            {
                "section_id": row["section_id"],
                "title": row["title"],
                "reason": "restricted_internal_not_for_customer_retrieval",
            }
            for row in rows
            if row["retrieval_policy"] == "excluded"
        ],
    }
    report = {
        "source_document": pdf_path.name,
        "source_sha256": source_hash,
        "page_count": page_count,
        "active_section_count": len(rows),
        "outdated_line_count": len(outdated_lines),
        "outdated_pages": audit["outdated_pages"],
        "audiences": dict(Counter(row["audience"] for row in rows)),
        "retrieval_policies": dict(Counter(row["retrieval_policy"] for row in rows)),
        "volatility": dict(Counter(row["volatility"] for row in rows)),
    }
    return rows, outdated_lines, {"audit": audit, "report": report}


def main() -> None:
    args = parse_args()
    pdf_path = Path(args.input).expanduser().resolve()
    if not pdf_path.is_file():
        raise SystemExit(f"PDF not found: {pdf_path}")
    rows, _, metadata = extract(pdf_path)

    output = Path(args.output).expanduser().resolve()
    audit_path = Path(args.audit).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    for path in (output, audit_path, report_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    audit_path.write_text(json.dumps(metadata["audit"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(metadata["report"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata["report"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
