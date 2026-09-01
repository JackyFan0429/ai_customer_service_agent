import unittest

from scripts.ingest_official_kb import validate


class OfficialIngestTests(unittest.TestCase):
    def test_internal_retrieval_policy_is_preserved(self):
        row = {
            "doc_id": "internal-1",
            "title": "Internal",
            "content": "Internal routing guidance",
            "authority": "official_internal_document",
            "source_url": "internal://source.pdf#page=1",
            "retrieved_at": "2026-09-01",
            "review_after": "2026-10-01",
            "volatility": "medium",
            "categories": ["other"],
            "keywords": [],
            "claims": [],
            "audience": "restricted_internal",
            "retrieval_policy": "excluded",
        }
        result = validate(row, __import__("pathlib").Path("source.jsonl"), 1)
        self.assertEqual(result["retrieval_policy"], "excluded")


if __name__ == "__main__":
    unittest.main()
