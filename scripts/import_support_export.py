#!/usr/bin/env python3
"""Convert a chat export to local, unreviewed cases and an aggregate behavior profile.

Raw exports and derived case text belong in ignored data/output. The shareable
profile contains counts and observable workflow patterns, never customer text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support_agent.desk.engine import EMAIL_RE, scrub


def redact(text):
    text = EMAIL_RE.sub("[EMAIL]", scrub(text))
    text = re.sub(r"https?://[^\s<>]+", "[URL]", text)
    text = re.sub(r"(?<!\w)@[A-Za-z0-9_]{3,}", "[HANDLE]", text)
    text = re.sub(r"\b\d{5,}\b", "[ID]", text)
    text = re.sub(r"(用户ID|工单ID|订阅|订单号|账号|手机号)[：:#\s]*[A-Za-z0-9_-]+", r"\1[ID]", text)
    return text


def analyze(source):
    messages = source.get("messages", [])
    by_id = {m["message_id"]: m for m in messages}
    groups = defaultdict(list)
    def root(m):
        seen, current = set(), m["message_id"]
        while current in by_id and by_id[current].get("reply_to_msg_id") and current not in seen:
            seen.add(current)
            current = by_id[current]["reply_to_msg_id"]
        return current
    runs, kinds, routes = [], Counter(), Counter()
    for m in messages:
        groups[root(m)].append(m)
        text = m.get("text") or ""
        if text.startswith("🤖 AI 草稿生成失败"):
            kinds["generation_failures"] += 1
        elif text.startswith("🤖 AI 已自动回复"):
            kinds["auto_replies"] += 1
        elif text.startswith("🤖 AI 草稿"):
            kinds["drafts"] += 1
        elif text.startswith("⚠️ 未自动发送"):
            kinds["held_drafts"] += 1
        if "人工 30 分钟" in text:
            kinds["human_cooldown_events"] += 1
        if text.startswith("⏰ 这单转人工"):
            kinds["handoff_reminders"] += 1
        match = re.search(r"🤖 AI (?:草稿|已自动回复) #(\d+)｜([^\n]+)", text)
        if match:
            tool = re.search(r"(\d+) 次工具调用", text)
            runs.append({"id": match[1], "route": match[2], "tool_count": int(tool[1]) if tool else None})
            routes[match[2]] += 1
    cases = []
    for index, (_, thread) in enumerate(groups.items(), 1):
        entries, events, incomplete = [], [], False
        for m in thread:
            text = m.get("text") or ""
            if text.startswith("用户："):
                role, content = "user", text[3:]
            elif text.startswith("客服："):
                role, content = "support", text[3:]
            elif text.startswith("🧾 新工单"):
                events.append("ticket_created")
                continue
            elif re.search(r"^(?:🤖|🧠|🔍|⚠️|⏰|⏳|📝|✅|ℹ️|/)", text) or not text:
                # Do not train on private notes, model scratchpads, or unshipped drafts.
                continue
            else:
                # Unlabelled senders cannot safely be assumed to be human support.
                events.append("unlabelled_message_excluded")
                continue
            if m.get("media_type") == "MessageMediaPhoto":
                incomplete = True
            entries.append({"message_id": m["message_id"], "role": role, "content": redact(content), "at": m.get("date_utc")})
        if not entries:
            continue
        first_user = next((m["content"] for m in entries if m["role"] == "user"), "")
        cases.append({"ticket_id": f"case-{index:04d}", "title": first_user[:100] or "缺少用户问题",
                      "messages": entries, "reviewed": False, "missing_media": incomplete,
                      "structure_confidence": "partial", "events": events,
                      "canonical_source_type": "chat_export", "usage": "review_before_training_or_retrieval"})
    profile = {"message_count": len(messages), "new_ticket_count": sum((m.get("text") or "").startswith("🧾 新工单已创建") for m in messages),
               "ai_run_count": len(runs), "runs_with_tools": sum((r["tool_count"] or 0)>0 for r in runs),
               "photo_count": sum(m.get("media_type") == "MessageMediaPhoto" for m in messages),
               "range": source.get("range"), "event_counts": dict(kinds), "route_counts": dict(routes),
               "candidate_case_count": len(cases), "reviewed_case_count": 0,
               "limitations": ["自动发送不等于问题已解决", "图片仅有类型标记，无图片内容", "草稿、内部备注与未知发言人不作为标准答案", "本项目未做模型参数微调"],
               "patterns": [
                   {"name": "先查数据再答复", "basis": "回复记录的工具调用计数与查询事件", "implementation": "当前工单用户绑定的数据库查询工具"},
                   {"name": "答复与部分转人工", "basis": "答复 + 部分转人工路由", "implementation": "多意图拆分与待人工事项"},
                   {"name": "草稿审核与自动回复", "basis": "九月草稿与后续自动回复事件", "implementation": "可切换审核/自动模式"},
                   {"name": "人工介入后不插话", "basis": "人工 30 分钟内回复的抑制事件", "implementation": "接管状态与可配置冷却时间"},
                   {"name": "质检与修订", "basis": "事实、遗漏诉求、转人工与操作承诺的质检记录", "implementation": "规则质检与可选模型审查"},
                   {"name": "转人工超时提醒", "basis": "等待超过 12 小时的提示", "implementation": "本地维护任务与提醒事件"},
                   {"name": "受约束的余额回正", "basis": "eligible 核验及执行结果事件", "implementation": "金额、来源、冷却期、幂等和发送时重验"}
               ]}
    return cases, profile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("data/output/chat_export"))
    p.add_argument("--profile", type=Path, help="Optional destination for the aggregate-only, shareable report")
    args = p.parse_args()
    data = args.input.read_bytes()
    cases, profile = analyze(json.loads(data))
    profile["source_sha256"] = hashlib.sha256(data).hexdigest()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "canonical_cases.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False)+"\n" for c in cases))
    (args.output / "profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2)+"\n")
    if args.profile:
        args.profile.parent.mkdir(parents=True, exist_ok=True)
        args.profile.write_text(json.dumps(profile, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"messages": profile["message_count"], "candidate_cases": len(cases), "reviewed": 0, "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
