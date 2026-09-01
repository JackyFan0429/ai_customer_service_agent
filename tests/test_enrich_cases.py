import unittest

from scripts.enrich_cases import enrich_case, extract_error_signatures


def base_case(**updates):
    case = {
        "ticket_id": "940",
        "structure_confidence": 1.0,
        "title": "Codex 连接失败",
        "description": "请求返回 502 service unavailable",
        "status": "closed",
        "messages": [
            {"role": "user", "content": "一直连接失败", "telegram_message_id": 1},
            {"role": "support", "content": "请检查代理配置并尝试切换网络", "telegram_message_id": 2},
            {"role": "user", "content": "切换后可以用了", "telegram_message_id": 3},
        ],
        "warnings": [],
        "canonical_source": "forum",
        "canonical_source_type": "original_forum",
        "case_quality": 90,
    }
    case.update(updates)
    return case


class EnrichmentTests(unittest.TestCase):
    def test_confirmed_case_keeps_evidence(self):
        _, result = enrich_case(base_case())
        self.assertEqual(result["resolution"]["status"], "user_confirmed_resolved")
        self.assertEqual(result["evidence"]["candidate_solution_message_ids"], [2])
        self.assertEqual(result["evidence"]["resolution_message_ids"], [3])
        self.assertEqual(result["quality"]["semantic_tier"], "verified_case")
        self.assertEqual(result["quality"]["retrieval_status"], "eligible")

    def test_closed_is_not_proof_of_resolution(self):
        case = base_case(messages=base_case()["messages"][:2])
        _, result = enrich_case(case)
        self.assertEqual(result["resolution"]["status"], "closed_without_user_confirmation")
        self.assertLess(result["resolution"]["confidence"], 0.5)

    def test_test_ticket_is_excluded(self):
        case = base_case(title="测试工单", description="123123")
        _, result = enrich_case(case)
        self.assertEqual(result["quality"]["semantic_tier"], "archive_only")
        self.assertEqual(result["quality"]["retrieval_status"], "excluded")

    def test_uncertain_flattened_case_requires_review(self):
        case = base_case(
            canonical_source_type="flattened_sequential",
            structure_confidence=0.6,
            warnings=["next_ticket_started_before_close"],
        )
        _, result = enrich_case(case)
        self.assertEqual(result["quality"]["retrieval_status"], "review_required")
        self.assertIn("flattened_boundary_uncertain", result["quality"]["review_reasons"])

    def test_error_signatures_are_deduplicated(self):
        errors = extract_error_signatures("HTTP 502 service unavailable; status 502")
        self.assertIn("HTTP 502", errors)
        self.assertIn("service unavailable", [x.lower() for x in errors])

    def test_support_fallback_does_not_replace_user_intent(self):
        case = base_case(
            title="Codex 连接失败",
            description="请求返回 502",
            messages=[
                {"role": "user", "content": "一直连接失败", "telegram_message_id": 1},
                {"role": "support", "content": "如果仍然失败可以申请退款", "telegram_message_id": 2},
            ],
        )
        _, result = enrich_case(case)
        self.assertEqual(result["primary_category"], "availability_network")

    def test_content_injection_is_quarantined(self):
        case = base_case(title='<script>alert("x")</script>')
        _, result = enrich_case(case)
        self.assertEqual(result["quality"]["semantic_tier"], "archive_only")
        self.assertIn("content_injection_risk", result["quality"]["review_reasons"])

    def test_processing_acknowledgement_is_not_a_solution(self):
        case = base_case(
            messages=[
                {"role": "user", "content": "一直连接失败", "telegram_message_id": 1},
                {"role": "support", "content": "正在处理中～", "telegram_message_id": 2},
            ]
        )
        _, result = enrich_case(case)
        self.assertEqual(result["historical_solution_candidates"], [])

    def test_secondary_secret_redaction(self):
        case = base_case(
            description="配置密钥 nb_ABCdef1234567890_very_secret_value",
            messages=[
                {"role": "user", "content": "nb_ABCdef1234567890_very_secret_value 无法使用", "telegram_message_id": 1},
                {"role": "support", "content": "请更换密钥", "telegram_message_id": 2},
            ],
        )
        enriched, result = enrich_case(case)
        serialized = str(enriched)
        self.assertNotIn("nb_ABCdef1234567890_very_secret_value", serialized)
        self.assertIn("<API_KEY>", result["problem_summary"])


if __name__ == "__main__":
    unittest.main()
