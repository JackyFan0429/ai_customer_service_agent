import unittest
from datetime import date

from scripts.extract_pdf_official_kb import classify_policy, line_is_struck, normalize, review_deadline


class PdfKnowledgeTests(unittest.TestCase):
    def test_extracting_an_old_pdf_does_not_renew_its_policy(self):
        self.assertLess(review_deadline(date(2026, 9, 19), None, "high"), "2026-09-19")

    def test_verified_policy_gets_an_explicit_bounded_review_window(self):
        self.assertEqual(review_deadline(date(2026, 9, 19), date(2026, 9, 19), "high"), "2026-09-26")
        with self.assertRaises(ValueError):
            review_deadline(date(2026, 9, 19), date(2026, 9, 20), "high")

    def test_strike_intersection_marks_line(self):
        line = {
            "chars": [
                {"x0": 10, "x1": 20, "top": 100, "bottom": 112},
                {"x0": 21, "x1": 31, "top": 100, "bottom": 112},
            ]
        }
        strike = [{"x0": 8, "x1": 35, "top": 105, "bottom": 106}]
        self.assertTrue(line_is_struck(line, strike))

    def test_line_outside_strike_is_active(self):
        line = {"chars": [{"x0": 10, "x1": 20, "top": 100, "bottom": 112}]}
        strike = [{"x0": 8, "x1": 35, "top": 120, "bottom": 121}]
        self.assertFalse(line_is_struck(line, strike))

    def test_restricted_payment_section_is_excluded(self):
        audience, policy = classify_policy("4.1.3", "USDT payment")
        self.assertEqual(audience, "restricted_internal")
        self.assertEqual(policy, "excluded")

    def test_pdf_compatibility_characters_are_normalized(self):
        self.assertEqual(normalize("客⼾\x01"), "客戶")


if __name__ == "__main__":
    unittest.main()
