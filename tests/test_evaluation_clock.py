"""A fixed offline benchmark date must cover seeding and read-tool windows."""

import argparse
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from scripts import evaluate_desk
from support_agent.desk import storage, tools


class EvaluationClockTests(unittest.TestCase):
    def test_fixed_time_keeps_seed_expiry_and_recent_request_windows_consistent(self):
        instant = evaluate_desk.parse_as_of("2020-01-02T00:00:00+11:00")

        def inspect_fixture():
            db = storage.Database(":memory:")
            try:
                read = tools.LocalBusinessTools(db, 2, 1)
                self.assertEqual(12, read.call("get_recent_requests")["count"])
                subscription = read.call("get_subscriptions")["subscriptions"][0]
                self.assertEqual("2020-01-04T13:00:00+00:00", subscription["reset_at"])
                self.assertEqual(4_200_000, subscription["remaining_units"])
                self.assertTrue(read.call("check_balance_adjustment")["eligible"])
                self.assertTrue(read.call("search_kb", query="套餐额度")["documents"])
                return {"created_at": storage.now(), "business_now": storage.now()}
            finally:
                db.close()

        with patch.object(evaluate_desk, "evaluate", inspect_fixture):
            report = evaluate_desk.run_evaluation(instant)
        self.assertEqual("fixed", report["clock_mode"])
        self.assertEqual("2020-01-01T13:00:00+00:00", report["business_now"])
        self.assertEqual(report["business_now"], report["as_of"])
        self.assertNotEqual(report["as_of"], report["created_at"])

    def test_clock_restored_after_a_failed_evaluation(self):
        storage_clock, tools_clock = storage.datetime, tools.datetime
        with patch.object(evaluate_desk, "evaluate", side_effect=RuntimeError("fixture failure")):
            with self.assertRaises(RuntimeError):
                evaluate_desk.run_evaluation(datetime(2020, 1, 1, tzinfo=timezone.utc))
        self.assertIs(storage_clock, storage.datetime)
        self.assertIs(tools_clock, tools.datetime)

    def test_cli_requires_an_unambiguous_instant(self):
        for value in ["2026-11-04", "2026-11-04T00:00:00", "invalid"]:
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                evaluate_desk.parse_as_of(value)

    def test_default_run_keeps_the_existing_wall_clock(self):
        original = storage.datetime
        with patch.object(evaluate_desk, "evaluate", return_value={"total": 29, "passed": 29}):
            report = evaluate_desk.run_evaluation()
        self.assertEqual("wall", report["clock_mode"])
        self.assertIsNone(report["as_of"])
        self.assertIs(original, storage.datetime)
        self.assertEqual(29, report["passed"])
