import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch

from support_agent.agent import CustomerAgent
from support_agent.config import AgentConfig
from support_agent.database import ConversationDatabase
from support_agent.models import Intent, QueryUnderstanding, Route
from support_agent.prompts import build_model_input
from support_agent.providers import LocalProvider
from support_agent.session import SessionStore, Turn
from support_agent.web import WebApplication
from scripts.evaluate_agent import grade_turn, summarize
from scripts.review_knowledge import build_review


class CaptureProvider(LocalProvider):
    def __init__(self):
        super().__init__(name="capture")
        self.input = None

    def generate(self, query, evidence, max_chars):
        self.input = json.loads(build_model_input(query, evidence, max_chars))
        return "已依据提供的资料回答。"


class RegressionTests(unittest.TestCase):
    def make_agent(self, ids, provider=None, **options):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        source = AgentConfig().corpus_path
        rows = [json.loads(line) for line in source.read_text().splitlines()]
        path = Path(temp.name) / "corpus.jsonl"
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows if row["document_id"] in {"demo:" + key for key in ids}))
        return CustomerAgent(AgentConfig(corpus_path=path, **options), provider=provider, today=date(2026, 9, 19))

    def test_complete_error_identifiers(self):
        for query, docs, route in [
            ("ClientB Code 401", ["1401"], Route.CLARIFY),
            ("ClientC Client E401", ["e4012"], Route.CLARIFY),
            ("ClientC Client 401", ["e401"], Route.CLARIFY),
            ("ClientC Client E401.", ["e401"], Route.ANSWER),
            ("ClientB Code (401)", ["401"], Route.ANSWER),
        ]:
            with self.subTest(query=query):
                self.assertEqual(self.make_agent(docs).respond(query).route, route)

    def test_short_code_change_replaces_old_code(self):
        agent = self.make_agent(["401", "503"])
        agent.respond("ClientB Code 401", session_id="a")
        response = agent.respond("现在变成 503 了", session_id="a")
        self.assertEqual([c["document_id"] for c in response.citations], ["demo:503"])
        self.assertNotIn("鉴权配置", response.answer)

    def test_failed_attempt_requests_new_information_in_context(self):
        agent = self.make_agent(["401"])
        agent.respond("ClientB Code 401", session_id="a")
        response = agent.respond("还是不行", session_id="a")
        self.assertEqual(response.route, Route.CLARIFY)
        self.assertIn("401", response.answer)
        self.assertIn("已经尝试", response.answer)

    def test_sessions_do_not_share_topics(self):
        agent = self.make_agent(["401", "503"])
        agent.respond("ClientB Code 401", session_id="a")
        response = agent.respond("还是不行", session_id="b")
        self.assertEqual(response.route, Route.CLARIFY)
        self.assertNotIn("401", response.answer)

    def test_restored_user_history_resolves_followups_without_assistant_codes(self):
        agent = self.make_agent(["401", "503"])
        agent.sessions.replace("a", [Turn("user", "ClientB Code 401"), Turn("assistant", "另一个示例曾提到 1401")])
        response = agent.respond("现在是 503", session_id="a")
        self.assertEqual([c["document_id"] for c in response.citations], ["demo:503"])

    def test_database_reload_preserves_followup_subject(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db = ConversationDatabase(Path(temp.name) / "test.db")
        app = WebApplication(self.make_agent(["401", "503"]), db)
        _, conversation = app.create_conversation({})
        app.send_message(conversation["id"], {"content": "ClientB Code 401"})
        restarted = WebApplication(self.make_agent(["401", "503"]), db)
        _, response = restarted.send_message(conversation["id"], {"content": "现在变成 503"})
        self.assertEqual(response["assistant_message"]["citations"][0]["document_id"], "demo:503")

    def test_new_topic_does_not_inherit_previous_error(self):
        agent = self.make_agent(["401", "invoice"])
        agent.respond("ClientB Code 401", session_id="a")
        response = agent.respond("发票申请流程是什么？", session_id="a")
        self.assertEqual([c["document_id"] for c in response.citations], ["demo:invoice"])

    def test_generator_receives_self_contained_query(self):
        provider = CaptureProvider()
        agent = self.make_agent(["401", "503"], provider)
        agent.respond("ClientB Code 401", session_id="a")
        agent.respond("现在是 503", session_id="a")
        question = provider.input["customer_question"]
        self.assertIn("ClientB Code", question)
        self.assertIn("503", question)
        self.assertNotIn("401", question)

    def test_model_rewrite_cannot_drop_an_explicit_code(self):
        provider = CaptureProvider()
        provider.understand = lambda query, context: QueryUnderstanding(Intent.SUPPORT_QUESTION, "ClientB Code", True, "", 0.9)
        response = self.make_agent(["401"], provider).respond("ClientB Code 502")
        self.assertEqual(response.route, Route.CLARIFY)
        self.assertIsNone(provider.input)

    def test_account_request_overrides_misclassified_greeting(self):
        provider = CaptureProvider()
        provider.understand = lambda query, context: QueryUnderstanding(Intent.GREETING_IDENTITY, query, False, "", 0.9)
        response = self.make_agent(["refund"], provider).respond("你好，你是谁，帮我退款")
        self.assertEqual(response.route, Route.ESCALATE)
        self.assertIsNone(provider.input)

    def test_refund_policy_and_personal_action_are_distinct(self):
        agent = self.make_agent(["refund"])
        self.assertEqual(agent.respond("退款政策是什么？").route, Route.ANSWER)
        self.assertEqual(agent.respond("帮我退款").route, Route.ESCALATE)
        self.assertEqual(agent.respond("退款").route, Route.CLARIFY)

    def test_citations_match_budgeted_model_input(self):
        provider = CaptureProvider()
        agent = self.make_agent(["401", "503"], provider, max_evidence_chars=5)
        response = agent.respond("ClientB Code")
        sent = provider.input["public_evidence"]
        self.assertEqual([c["document_id"] for c in response.citations], [r["document_id"] for r in sent])
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(sent[0]["text"]), 5)

    def test_calendar_expiry_is_rechecked_without_restart(self):
        agent = self.make_agent(["expiry_boundary"])
        agent.today = None
        with patch("support_agent.agent.date") as clock:
            clock.today.side_effect = [date(2026, 9, 19), date(2026, 9, 20)]
            self.assertEqual(agent.respond("ClientD 配置说明").route, Route.ANSWER)
            self.assertEqual(agent.respond("ClientD 配置说明").route, Route.CLARIFY)

    def test_demo_default_is_packaged_and_requires_no_private_corpus(self):
        config = AgentConfig()
        config.validate()
        self.assertTrue(config.corpus_path.is_absolute())
        response = CustomerAgent(config).respond("ClientA Base URL 配置")
        self.assertEqual(response.route, Route.ANSWER)
        self.assertIn("虚构演示", response.answer)

    def test_review_queue_never_renews_expired_rows(self):
        rows = [dict(document_id="x", precedence="P1", audience="customer_safe", review_after="2026-09-18", text="old policy")]
        summary, queue = build_review(rows, date(2026, 9, 19))
        self.assertEqual(summary["pending_review"], 1)
        self.assertEqual(queue[0]["review_state"], "pending_source_verification")
        self.assertIsNone(queue[0]["verified_at"])
        self.assertEqual(rows[0]["review_after"], "2026-09-18")

    def test_evaluation_rejects_wrong_evidence_and_forbidden_claim(self):
        expected = dict(route="answer", evidence=["good"], allowed_evidence=["good"], required_points=[["检查"]], forbidden=["已经退款"])
        actual = dict(route="answer", answer="检查后已经退款", citations=[{"document_id": "wrong"}])
        grade = grade_turn(expected, actual)
        self.assertFalse(grade["passed"])
        self.assertFalse(grade["checks"]["allowed_evidence"])
        self.assertFalse(grade["checks"]["forbidden_claims"])

    def test_evaluation_does_not_hide_failed_turns_in_task_average(self):
        expected = dict(route="escalate", evidence=[])
        good = dict(expected=expected, actual={"route": "escalate", "citations": []}, checks={"route": True}, passed=True)
        bad = dict(expected=expected, actual={"route": "error", "citations": []}, checks={"route": False}, passed=False)
        summary = summarize([dict(turns=[good, bad], passed=False)])
        self.assertEqual(summary["scenario_pass"]["rate"], 0)
        self.assertEqual(summary["route_accuracy"]["rate"], 0.5)
        self.assertEqual(summary["escalation_recall"]["denominator"], 2)


if __name__ == "__main__":
    unittest.main()
