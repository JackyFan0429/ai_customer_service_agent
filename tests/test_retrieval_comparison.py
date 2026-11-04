"""Check benchmark arithmetic, split order and production-default parity."""

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from scripts import evaluate_retrieval as evaluation
from support_agent.desk.storage import Database
from support_agent.desk.tools import LocalBusinessTools
from support_agent.retrieval import search


def case(kind="kb_answerable", gold=None):
    return {"id": "unit-case", "group_id": "unit-group", "query": "abcdef",
            "tags": ["unit"], "answerability": kind,
            "relevant_ids": ["a", "b"] if gold is None else gold}


def candidate(key, coverage=0.5):
    return {"document_id": key, "title": key, "score": 1.0, "lexical_score": 1.0,
            "semantic_ngram_score": 0.5, "authority_boost": 0.0, "query_term_coverage": coverage}


class RetrievalComparisonTests(unittest.TestCase):
    def test_default_matches_unmodified_v055_results(self):
        fixture = json.loads((evaluation.ROOT / "tests/fixtures/retrieval-v055-default.json").read_text())
        for item in fixture["cases"]:
            with self.subTest(query=item["query"]):
                self.assertEqual(item["expected"], search(fixture["corpus"], item["query"], item["top_k"]))
                self.assertEqual(item["expected"], search(fixture["corpus"], item["query"], item["top_k"], method="hybrid"))

    def test_character_similarity_can_find_an_unmatched_word(self):
        corpus = [{"document_id": "a", "text": "abcdef", "precedence": "P2"}]
        self.assertEqual([], search(corpus, "abcdeg", 4, method="bm25"))
        self.assertEqual("a", search(corpus, "abcdeg", 4, method="char_ngram")[0]["document_id"])

    def test_unknown_method_is_rejected_even_for_empty_corpus(self):
        with self.assertRaises(ValueError):
            search([], "x", 4, method="typo")

    def test_partial_multidocument_recall_and_first_relevant_rank(self):
        row = evaluation.score_case(case(), [candidate("noise"), candidate("b")])
        self.assertEqual(0.5, row["recall"])
        self.assertEqual(0.5, row["reciprocal_rank"])
        self.assertEqual(0.5, row["returned_precision"])
        self.assertFalse(row["full_recall"])
        self.assertEqual({"a": "not_ranked"}, row["missed_relevant"])

    def test_coverage_filter_does_not_refill_from_rank_five(self):
        ranked = [candidate("a", 0.119999), candidate("x"), candidate("y"), candidate("z"), candidate("b")]
        row = evaluation.score_case(case(), ranked)
        self.assertEqual(["x", "y", "z"], row["final_ids"])
        self.assertEqual({"a": "coverage_filter", "b": "outside_top_k"}, row["missed_relevant"])
        boundary = evaluation.score_case(case(gold=["a"]), [candidate("a", 0.12)])
        self.assertEqual(["a"], boundary["final_ids"])

    def test_macro_recall_does_not_weight_multi_document_queries_more(self):
        rows = [evaluation.score_case(case(), [candidate("a")]),
                evaluation.score_case(case(gold=["c"]), [])]
        metric = evaluation.summarize(rows)["recall_at_4"]
        self.assertEqual({"numerator": 0.5, "denominator": 2, "rate": 0.25}, metric)

    def test_exceptions_stay_in_denominators_and_are_not_successful_abstentions(self):
        rows = [evaluation.score_case(case(), [], error="RuntimeError"),
                evaluation.score_case(case("no_kb_answer", []), [], error="RuntimeError"),
                evaluation.score_case(case("no_kb_answer", []), [candidate("noise")])]
        metrics = evaluation.summarize(rows)
        self.assertEqual(1, metrics["recall_at_4"]["denominator"])
        self.assertEqual(0, metrics["recall_at_4"]["rate"])
        self.assertEqual(0.5, metrics["no_answer_false_retrieval"]["rate"])
        self.assertEqual({"returned_irrelevant": 1, "successful_empty": 0, "exceptions": 1}, metrics["no_answer_outcomes"])
        self.assertEqual(2, metrics["retrieval_exceptions"]["numerator"])

    def test_dynamic_queries_are_diagnostic_only_and_empty_populations_are_null(self):
        row = evaluation.score_case(case("business_data_only", []), [candidate("noise")])
        metrics = evaluation.summarize([row])
        self.assertIsNone(metrics["recall_at_4"]["rate"])
        self.assertIsNone(metrics["no_answer_false_retrieval"]["rate"])
        self.assertEqual({"questions": 1, "nonempty_results": 1}, metrics["dynamic_diagnostics"])

    def test_ranker_only_receives_query_and_records_each_failed_method(self):
        query = case()
        query["rationale"] = "Do not give this gold evidence to the ranker"
        with patch.object(evaluation, "search", side_effect=RuntimeError("fixture")) as ranker:
            report = evaluation.evaluate_cases([], [query])
        self.assertEqual(3, ranker.call_count)
        for call in ranker.call_args_list:
            self.assertEqual(([], "abcdef", 1), call.args)
        for method in evaluation.METHODS:
            self.assertEqual(1, report[method]["metrics"]["retrieval_exceptions"]["numerator"])

    def test_development_does_not_read_holdout_queries(self):
        original_text, original_bytes = Path.read_text, Path.read_bytes
        def read_text(path, *args, **kwargs):
            self.assertNotEqual("holdout.jsonl", path.name)
            return original_text(path, *args, **kwargs)
        def read_bytes(path, *args, **kwargs):
            self.assertNotEqual("holdout.jsonl", path.name)
            return original_bytes(path, *args, **kwargs)
        with patch.object(Path, "read_text", read_text), patch.object(Path, "read_bytes", read_bytes):
            _, _, cases = evaluation.load_split(evaluation.DEFAULT_DATASET, "development")
            evaluation.identity(evaluation.DEFAULT_DATASET)
        self.assertEqual(20, len(cases))

    def test_holdout_requires_freeze_before_loading_questions(self):
        with patch.object(evaluation, "load_split") as loader:
            with self.assertRaisesRegex(ValueError, "requires --freeze"):
                evaluation.run_evaluation(split="holdout")
        loader.assert_not_called()

    def test_freeze_rejects_later_parameter_changes_before_loading_holdout(self):
        with tempfile.TemporaryDirectory() as temp:
            frozen = {"kind": "retrieval_freeze", "development_preference": "hybrid",
                      "identity": copy.deepcopy(evaluation.identity(evaluation.DEFAULT_DATASET))}
            frozen["identity"]["configuration"]["minimum_query_term_coverage"] = 0.5
            path = Path(temp) / "frozen.json"
            path.write_text(json.dumps(frozen))
            with patch.object(evaluation, "load_split") as loader:
                with self.assertRaisesRegex(ValueError, "changed since freeze"):
                    evaluation.run_evaluation(split="holdout", freeze_path=path)
            loader.assert_not_called()

    def test_frozen_snapshot_ranker_results_match_historical_filter(self):
        _, corpus, _ = evaluation.load_split(evaluation.DEFAULT_DATASET, "development")
        db = Database(":memory:")
        try:
            # Production policy text changed in v0.5.8. Compare the ranker on
            # identical frozen inputs; do not label old scores as new-policy results.
            for doc in corpus:
                db.execute('UPDATE knowledge SET title=?,content=?,keywords=?,category=? WHERE id=?',
                           (doc['title'], doc['text'], json.dumps(doc['keywords']), doc['categories'][0], doc['document_id']))
            for query in ("套餐额度", "401 Key", "无关词XYZ"):
                tool = LocalBusinessTools(db, 2, 1)
                actual = [r["document_id"] for r in search(corpus, query, 4) if r["query_term_coverage"] >= 0.12]
                task = case(gold=[]); task["query"] = query; task["answerability"] = "business_data_only"
                ranked = search(corpus, query, len(corpus), method="hybrid")
                self.assertEqual(actual, evaluation.score_case(task, ranked)["final_ids"])
        finally:
            db.close()

    def test_existing_output_stops_before_any_retrieval(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "existing.json"; path.write_text("preserve me")
            with patch.object(evaluation.sys, "argv", ["evaluate_retrieval.py", "development", "--output", str(path)]), patch.object(evaluation, "run_evaluation") as runner:
                with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit_context:
                    evaluation.main()
                self.assertEqual(2, exit_context.exception.code)
            runner.assert_not_called()
            self.assertEqual("preserve me", path.read_text())

    def test_holdout_keeps_the_development_choice(self):
        task = case(gold=["a"])
        task["review"] = {"status": "pending_owner_review"}
        frozen = {"development_preference": "hybrid", "created_at": "2026-11-04T00:00:00+00:00"}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "freeze.json"; path.write_text("unit fixture")
            with patch.object(evaluation, "verify_freeze", return_value=frozen), patch.object(evaluation, "load_split", return_value=({}, [], [task])), patch.object(evaluation, "evaluate_cases", return_value={"bm25": "pretend winner"}):
                report = evaluation.run_evaluation(split="holdout", freeze_path=path)
        self.assertEqual("hybrid", report["development_preference"])
        self.assertFalse(report["selection_updated_from_holdout"])


if __name__ == "__main__":
    unittest.main()
