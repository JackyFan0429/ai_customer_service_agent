"""Protect label evidence, benchmark populations and the reserved split."""

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import validate_retrieval_dataset as dataset


class RetrievalDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = dataset.DEFAULT_DATASET
        cls.manifest = json.loads((cls.directory / "manifest.json").read_text())
        cls.knowledge = json.loads((cls.directory / "knowledge.json").read_text())
        cls.cases = [json.loads(line) for split in dataset.SPLITS
                     for line in (cls.directory / f"{split}.jsonl").read_text().splitlines() if line]

    def check(self, cases, **kwargs):
        return dataset.validate_records(self.knowledge, cases, self.manifest["split_policy"]["groups"], **kwargs)

    def test_dataset_integrity_and_metric_populations(self):
        report = dataset.validate_dataset()
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(30, report["questions"])
        self.assertEqual(22, report["groups"])
        self.assertEqual(20, report["splits"]["development"]["questions"])
        self.assertEqual(10, report["splits"]["holdout"]["questions"])
        self.assertTrue(all(report["knowledge_coverage"].values()))
        self.assertEqual({"pending_owner_review": 30}, report["review_status"])
        self.assertEqual({"recall_at_4_and_mrr_at_4": 25, "no_answer_false_retrieval_rate": 3,
                          "dynamic_diagnostic_only": 2}, report["metric_population_sizes"])

    def test_same_problem_group_cannot_cross_splits(self):
        cases = copy.deepcopy(self.cases)
        cases[1]["split"] = "holdout"
        report = self.check(cases)
        self.assertFalse(report["valid"])
        self.assertTrue(any("group crosses" in e for e in report["errors"]))

    def test_duplicate_query_ignores_formatting(self):
        cases = copy.deepcopy(self.cases)
        cases[20]["query"] = "  " + cases[0]["query"].replace("？", " ? ")
        self.assertTrue(any("duplicate normalized query" in e for e in self.check(cases)["errors"]))

    def test_labels_need_existing_ids_and_complete_evidence(self):
        for change in ("unknown", "missing_evidence"):
            with self.subTest(change=change):
                cases = copy.deepcopy(self.cases)
                if change == "unknown":
                    cases[0]["relevant_ids"] = ["UNKNOWN-001"]
                else:
                    cases[16]["evidence"].pop()
                self.assertFalse(self.check(cases)["valid"])

    def test_quotes_must_be_in_the_frozen_source(self):
        cases = copy.deepcopy(self.cases)
        cases[0]["evidence"][0]["quote"] = "余额总是先扣，退款一定到账。"
        self.assertTrue(any("quote" in e for e in self.check(cases)["errors"]))

    def test_business_only_queries_cannot_silently_count_as_no_answer(self):
        cases = copy.deepcopy(self.cases)
        cases[19]["answerability"] = "no_kb_answer"
        report = self.check(cases)
        self.assertFalse(report["valid"])
        self.assertTrue(any("business-data requirement" in e for e in report["errors"]))

    def test_review_gate_requires_review_records(self):
        report = self.check(self.cases, require_reviewed=True)
        self.assertEqual(30, len(report["errors"]))
        cases = copy.deepcopy(self.cases)
        for case in cases:
            case["review"] = {"status": "approved", "reviewer": "Unit-test reviewer fixture", "reviewed_at": "2026-11-04"}
        self.assertTrue(self.check(cases, require_reviewed=True)["valid"])
        cases[0]["review"]["reviewed_at"] = None
        self.assertFalse(self.check(cases, require_reviewed=True)["valid"])

    def test_changed_snapshot_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "dataset"
            shutil.copytree(self.directory, target)
            path = target / "knowledge.json"
            path.write_text(path.read_text() + "\n")
            report = dataset.validate_dataset(target)
            self.assertFalse(report["valid"])
            self.assertTrue(any("SHA-256" in e for e in report["errors"]))

    def test_expired_snapshot_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "dataset"
            shutil.copytree(self.directory, target)
            manifest = copy.deepcopy(self.manifest)
            manifest["knowledge_state"]["review_after"] = "2026-11-02"
            (target / "manifest.json").write_text(json.dumps(manifest))
            report = dataset.validate_dataset(target)
            self.assertFalse(report["valid"])
            self.assertTrue(any("valid at the fixed instant" in e for e in report["errors"]))

    def test_validation_never_runs_rankings(self):
        with patch("support_agent.desk.tools.search") as portal_search, patch("support_agent.retrieval.search") as search:
            report = dataset.validate_dataset()
        self.assertTrue(report["valid"], report["errors"])
        portal_search.assert_not_called()
        search.assert_not_called()
        self.assertFalse(report["retrieval_executed"])

    def test_cli_reports_failure_for_missing_dataset(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "validation.json"
            result = subprocess.run([sys.executable, str(dataset.ROOT / "scripts/validate_retrieval_dataset.py"),
                                     "--dataset", temp, "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(1, result.returncode)
            self.assertFalse(json.loads(output.read_text())["valid"])


if __name__ == "__main__":
    unittest.main()
