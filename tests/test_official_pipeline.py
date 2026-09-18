import unittest

from scripts.check_case_conflicts import assess
from scripts.hybrid_search import search


OFFICIAL = {
    "doc_id": "official-clients",
    "title": "Supported clients",
    "content": "ClientA is listed as a supported integration.",
    "authority": "official_public_website",
    "source_url": "https://example.com",
    "volatility": "medium",
    "products": ["clienta"],
    "categories": ["configuration_integration"],
    "keywords": ["clienta", "配置"],
    "claims": [
        {
            "claim_id": "supports-clienta",
            "statement": "ClientA is supported.",
            "contradiction_patterns": [r"不支持.{0,10}clienta"],
        }
    ],
}


def case(solution: str = "请重新配置 ClientA"):
    return {
        "ticket_id": "1",
        "products": ["clienta"],
        "primary_category": "configuration_integration",
        "category_tags": ["configuration_integration"],
        "problem_summary": "ClientA 配置失败",
        "error_signatures": [],
        "historical_solution_candidates": [{"text": solution}],
    }


class OfficialPipelineTests(unittest.TestCase):
    def test_explicit_contradiction_is_blocked(self):
        result = assess(case("目前不支持 ClientA"), [OFFICIAL])
        self.assertEqual(result["status"], "potential_conflict")
        self.assertEqual(result["retrieval_policy"], "blocked_pending_review")

    def test_no_related_document_is_not_claimed_as_checked(self):
        item = case("请联系客服处理")
        item["products"] = ["unknown"]
        item["primary_category"] = "refund"
        item["category_tags"] = ["refund"]
        item["problem_summary"] = "申请退款"
        result = assess(item, [OFFICIAL])
        self.assertEqual(result["status"], "insufficient_official_coverage")

    def test_official_result_gets_authority_metadata(self):
        corpus = [
            {
                "document_id": "official:1",
                "precedence": "P1",
                "title": "ClientA 配置",
                "text": "配置 ClientA API Base URL",
                "categories": ["configuration_integration"],
                "products": ["clienta"],
            },
            {
                "document_id": "case:1",
                "precedence": "P2",
                "title": "ClientA 配置错误",
                "text": "历史配置案例",
                "categories": ["configuration_integration"],
                "products": ["clienta"],
            },
        ]
        results = search(corpus, "ClientA Base URL 配置", 2)
        self.assertEqual(results[0]["document_id"], "official:1")
        self.assertGreater(results[0]["authority_boost"], 0)

    def test_relevant_official_precedes_slightly_higher_case_score(self):
        corpus = [
            {
                "document_id": "official:1",
                "precedence": "P1",
                "title": "Support API 接入方式概览",
                "text": "通过 Base URL 和鉴权信息配置 ClientA。",
                "keywords": ["clienta", "base url", "配置"],
                "categories": ["configuration_integration"],
                "products": ["clienta"],
            },
            {
                "document_id": "case:1",
                "precedence": "P2",
                "title": "ClientA Base URL 配置失败",
                "text": "ClientA Base URL 配置失败 ClientA Base URL 配置失败",
                "keywords": ["clienta", "base url"],
                "categories": ["configuration_integration"],
                "products": ["clienta"],
            },
        ]
        results = search(corpus, "ClientA 怎么配置 Base URL", 2)
        self.assertEqual(results[0]["document_id"], "official:1")


if __name__ == "__main__":
    unittest.main()
