import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from krill_agent.agent import CustomerAgent
from krill_agent.config import AgentConfig
from krill_agent.models import Route
from krill_agent.policy import IDENTITY_RESPONSE, select_evidence


def record(**overrides):
    base = {
        "document_id": "official:setup",
        "document_type": "official_knowledge",
        "authority": "official_public_website",
        "precedence": "P1",
        "title": "Codex Base URL 配置",
        "text": "在 Codex 设置中填写官方页面显示的 Base URL，然后重新登录。",
        "products": ["codex"],
        "clients": ["codex_cli"],
        "categories": ["configuration_integration"],
        "keywords": ["Codex", "Base URL", "配置"],
        "source_url": "https://example.test/setup",
        "review_after": "2026-09-08",
        "audience": "customer_safe",
        "conflict_status": "authoritative_source",
        "generation_policy": "may_support_current_facts_until_review_after",
    }
    base.update(overrides)
    return base


class StubProvider:
    name = "stub"

    def __init__(self):
        self.evidence = []

    def generate(self, query, evidence, max_chars):
        self.evidence = evidence
        return "已根据公开证据回答。"


class AgentTests(unittest.TestCase):
    def make_agent(self, rows, provider=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "corpus.jsonl"
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        config = AgentConfig(corpus_path=path, min_score=0.01)
        return CustomerAgent(config, provider=provider, today=date(2026, 9, 1))

    def test_official_evidence_is_used_before_history(self):
        provider = StubProvider()
        history = record(
            document_id="case:1",
            authority="historical_case",
            precedence="P2",
            title="历史配置案例",
            text="历史客服曾建议修改配置。",
            audience=None,
            review_after=None,
            conflict_status="no_rule_conflict_detected",
            generation_policy="historical_troubleshooting_evidence_only",
        )
        agent = self.make_agent([history, record()], provider)
        response = agent.respond("Codex Base URL 怎么配置？")
        self.assertEqual(response.route, Route.ANSWER)
        self.assertEqual(provider.evidence[0].precedence, "P1")

    def test_internal_text_never_reaches_provider_or_citations(self):
        provider = StubProvider()
        internal = record(
            document_id="official:internal",
            title="内部处理流程",
            text="秘密内部流程，不得公开。",
            authority="official_internal_document",
            audience="agent_internal",
            generation_policy="may_inform_internal_routing_not_disclose_verbatim",
        )
        agent = self.make_agent([record(), internal], provider)
        response = agent.respond("Codex Base URL 怎么配置？")
        self.assertTrue(provider.evidence)
        self.assertFalse(any(item.audience == "agent_internal" for item in provider.evidence))
        self.assertFalse(any(item["document_id"] == "official:internal" for item in response.citations))

    def test_local_internal_source_uri_is_not_disclosed(self):
        provider = StubProvider()
        safe_internal = record(
            source_url="internal://ticket-kb.pdf#pages=1-1",
            authority="official_internal_document",
        )
        agent = self.make_agent([safe_internal], provider)
        response = agent.respond("Codex Base URL 怎么配置？")
        self.assertEqual(response.route, Route.ANSWER)
        self.assertIsNone(response.citations[0]["source_url"])

    def test_expired_official_and_risky_history_are_filtered(self):
        rows = [
            record(review_after="2026-08-31"),
            record(
                document_id="case:stale",
                authority="historical_case",
                precedence="P2",
                audience=None,
                review_after=None,
                conflict_status="potentially_outdated_current_fact",
                generation_policy="historical_troubleshooting_evidence_only",
            ),
        ]
        scored = [{"score": 0.8, **row} for row in rows]
        public, internal = select_evidence(scored, today=date(2026, 9, 1), min_score=0.1)
        self.assertEqual(public, [])
        self.assertEqual(internal, [])

    def test_account_specific_request_escalates_without_generation(self):
        provider = StubProvider()
        agent = self.make_agent([record()], provider)
        response = agent.respond("帮我查一下我的订单为什么还没到账")
        self.assertEqual(response.route, Route.ESCALATE)
        self.assertEqual(provider.evidence, [])
        self.assertIn("不要发送密码", response.answer)

    def test_vague_question_requests_clarification(self):
        agent = self.make_agent([record()])
        response = agent.respond("用不了")
        self.assertEqual(response.route, Route.CLARIFY)
        self.assertIn("完整报错", response.answer)

    def test_local_provider_cites_only_the_evidence_it_renders(self):
        history = record(
            document_id="case:1",
            authority="historical_case",
            precedence="P2",
            audience=None,
            review_after=None,
            conflict_status="no_rule_conflict_detected",
            generation_policy="historical_troubleshooting_evidence_only",
        )
        agent = self.make_agent([record(), history])
        response = agent.respond("Codex Base URL 怎么配置？")
        self.assertEqual(len(response.citations), 1)
        self.assertEqual(response.citations[0]["document_id"], "official:setup")

    def test_live_status_request_escalates(self):
        agent = self.make_agent([record()])
        response = agent.respond("今天服务是不是挂了？")
        self.assertEqual(response.route, Route.ESCALATE)
        self.assertIn("实时服务状态", response.reason)

    def test_identity_question_without_punctuation_uses_standard_response(self):
        provider = StubProvider()
        agent = self.make_agent([record()], provider)
        response = agent.respond("你是谁")
        self.assertEqual(response.route, Route.ANSWER)
        self.assertEqual(response.answer, IDENTITY_RESPONSE)
        self.assertEqual(response.citations, [])
        self.assertEqual(provider.evidence, [])

    def test_identity_question_with_punctuation_has_same_response(self):
        provider = StubProvider()
        agent = self.make_agent([record()], provider)
        response = agent.respond("你是谁？")
        self.assertEqual(response.answer, IDENTITY_RESPONSE)
        self.assertEqual(provider.evidence, [])

    def test_out_of_domain_question_clarifies_without_generation(self):
        provider = StubProvider()
        agent = self.make_agent([record()], provider)
        response = agent.respond("怎么在月球上用 Krill 煮咖啡？")
        self.assertEqual(response.route, Route.CLARIFY)
        self.assertIn("没有从知识库中找到", response.answer)
        self.assertIn("已经尝试的步骤", response.answer)
        self.assertEqual(provider.evidence, [])

    def test_error_code_must_appear_in_evidence(self):
        provider = StubProvider()
        claude_without_401 = record(
            title="Claude Code connection setup",
            text="Configure Claude Code using the current setup guide.",
            products=["claude"],
            clients=["claude_code"],
            keywords=["Claude", "Code", "connection"],
        )
        agent = self.make_agent([claude_without_401], provider)
        response = agent.respond("Claude Code 报 401 怎么办？")
        self.assertEqual(response.route, Route.CLARIFY)
        self.assertEqual(provider.evidence, [])

    def test_matching_error_code_can_reach_provider(self):
        provider = StubProvider()
        claude_with_401 = record(
            title="Claude Code 401 error",
            text="A Claude Code 401 error can indicate invalid authentication configuration.",
            products=["claude"],
            clients=["claude_code"],
            keywords=["Claude", "Code", "401", "authentication"],
        )
        agent = self.make_agent([claude_with_401], provider)
        response = agent.respond("Claude Code 报 401 怎么办？")
        self.assertEqual(response.route, Route.ANSWER)
        self.assertTrue(provider.evidence)


if __name__ == "__main__":
    unittest.main()
