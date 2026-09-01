import unittest

from scripts.extract_pdf_official_kb import classify_policy, line_is_struck, normalize


class PdfKnowledgeTests(unittest.TestCase):
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

