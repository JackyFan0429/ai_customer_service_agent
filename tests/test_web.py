import tempfile
import unittest
from pathlib import Path

from krill_agent.database import ConversationDatabase
from krill_agent.models import AgentResponse, Route
from krill_agent.session import SessionStore
from krill_agent.web import WebApplication


class FakeProvider:
    name = "fake"


class FakeAgent:
    def __init__(self):
        self.sessions = SessionStore()
        self.provider = FakeProvider()

    def respond(self, query, session_id=None):
        return AgentResponse(
            answer=f"Grounded answer for: {query}",
            route=Route.ANSWER,
            reason="test evidence",
            citations=[{"document_id": "official:test", "title": "Test source"}],
            session_id=session_id,
            provider="fake",
        )


class WebApplicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        database = ConversationDatabase(Path(temporary.name) / "web.db")
        self.application = WebApplication(FakeAgent(), database)

    def test_create_send_and_reload_history(self):
        status, conversation = self.application.create_conversation({})
        self.assertEqual(status, 201)

        status, payload = self.application.send_message(
            conversation["id"],
            {"content": "How do I configure Codex?"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(payload["user_message"]["role"], "user")
        self.assertEqual(payload["assistant_message"]["role"], "assistant")

        status, history = self.application.get_messages(conversation["id"])
        self.assertEqual(status, 200)
        self.assertEqual(len(history["messages"]), 2)
        self.assertEqual(history["conversation"]["title"], "How do I configure Codex?")

    def test_empty_message_is_rejected(self):
        _, conversation = self.application.create_conversation({})
        status, payload = self.application.send_message(conversation["id"], {"content": "  "})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_unknown_conversation_returns_not_found(self):
        status, _ = self.application.get_messages("0" * 32)
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
