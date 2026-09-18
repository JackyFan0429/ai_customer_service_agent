import tempfile
import unittest
from pathlib import Path

from support_agent.database import ConversationDatabase


class ConversationDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "history.db"
        self.database = ConversationDatabase(self.path)

    def test_conversation_and_messages_persist_across_instances(self):
        conversation = self.database.create_conversation()
        self.database.add_message(conversation["id"], "user", "How do I configure ClientA?")
        self.database.add_message(
            conversation["id"],
            "assistant",
            "Open the setup guide.",
            route="answer",
            citations=[{"document_id": "official:setup"}],
        )

        reopened = ConversationDatabase(self.path)
        conversations = reopened.list_conversations()
        messages = reopened.list_messages(conversation["id"])

        self.assertEqual(len(conversations), 1)
        self.assertEqual(conversations[0]["message_count"], 2)
        self.assertEqual(messages[1].route, "answer")
        self.assertEqual(messages[1].citations[0]["document_id"], "official:setup")

    def test_deleting_conversation_cascades_messages(self):
        conversation = self.database.create_conversation("Temporary")
        self.database.add_message(conversation["id"], "user", "Question")
        self.assertTrue(self.database.delete_conversation(conversation["id"]))
        self.assertEqual(self.database.list_messages(conversation["id"]), [])


if __name__ == "__main__":
    unittest.main()
