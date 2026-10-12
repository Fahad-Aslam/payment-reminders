"""Run from inside python/:  python -m unittest"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from plan import build_plan, format_message, parse_iso_date

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def inv(**kwargs):
    base = {
        "id": "INV-1",
        "customer": "Acme",
        "email": "a@example.test",
        "amount": 100.0,
        "currency": "EUR",
        "due_date": "2026-10-01",
        "paid_date": None,
    }
    base.update(kwargs)
    return base


class ParseDateTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_iso_date("2026-10-12").isoformat(), "2026-10-12")

    def test_rejects_bad_calendar_and_formats(self):
        self.assertIsNone(parse_iso_date("2026-02-30"))
        self.assertIsNone(parse_iso_date("30/09/2026"))
        self.assertIsNone(parse_iso_date(""))
        self.assertIsNone(parse_iso_date(None))


class ShapeTest(unittest.TestCase):
    def test_empty_input_gives_empty_plan(self):
        plan = build_plan([], [], "2026-10-12")
        self.assertEqual(plan, {"today": "2026-10-12", "actions": [], "skipped": []})


class BadDataTest(unittest.TestCase):
    def test_duplicate_id_listed_once(self):
        plan = build_plan(
            [inv(id="INV-D", amount=10), inv(id="INV-D", amount=-1)],
            [],
            "2026-10-12",
        )
        self.assertEqual(plan["skipped"], [{"invoice_id": "INV-D", "reason": "duplicate_id"}])
        self.assertEqual(plan["actions"], [])

    def test_invalid_amount_variants(self):
        cases = [
            inv(amount="100"),
            inv(amount=True),
            {k: v for k, v in inv().items() if k != "amount"},
            inv(amount=0),
            inv(amount=-5),
        ]
        for case in cases:
            with self.subTest(amount=case.get("amount", "<missing>")):
                plan = build_plan([case], [], "2026-10-12")
                self.assertEqual(plan["skipped"][0]["reason"], "invalid_amount")

    def test_missing_due_date(self):
        for due in (None, ""):
            plan = build_plan([inv(due_date=due)], [], "2026-10-12")
            self.assertEqual(plan["skipped"][0]["reason"], "missing_due_date")
        missing = {k: v for k, v in inv().items() if k != "due_date"}
        plan = build_plan([missing], [], "2026-10-12")
        self.assertEqual(plan["skipped"][0]["reason"], "missing_due_date")

    def test_invalid_due_date(self):
        for due in ("2026-02-30", "30/09/2026"):
            plan = build_plan([inv(due_date=due)], [], "2026-10-12")
            self.assertEqual(plan["skipped"][0]["reason"], "invalid_due_date")

    def test_invalid_paid_date(self):
        plan = build_plan([inv(paid_date="")], [], "2026-10-12")
        self.assertEqual(plan["skipped"][0]["reason"], "invalid_paid_date")
        plan = build_plan([inv(paid_date="2026-10-13")], [], "2026-10-12")
        self.assertEqual(plan["skipped"][0]["reason"], "invalid_paid_date")


class RulesTest(unittest.TestCase):
    def test_paid_with_prior_sent_plans_nothing(self):
        plan = build_plan(
            [inv(id="INV-P", paid_date="2026-10-05", due_date="2026-09-01")],
            [{"invoice_id": "INV-P", "step": "friendly", "sent_on": "2026-09-10"}],
            "2026-10-12",
        )
        self.assertEqual(plan["actions"], [])
        self.assertEqual(plan["skipped"], [])

    def test_overdue_thresholds(self):
        today = "2026-10-12"
        expectations = [
            ("2026-10-12", None),
            ("2026-10-10", None),
            ("2026-10-09", "friendly"),
            ("2026-10-02", "firm"),
            ("2026-09-18", "final"),
        ]
        for due, step in expectations:
            with self.subTest(due=due):
                plan = build_plan([inv(id="INV-T", due_date=due)], [], today)
                if step is None:
                    self.assertEqual(plan["actions"], [])
                else:
                    self.assertEqual(len(plan["actions"]), 1)
                    self.assertEqual(plan["actions"][0]["step"], step)
                    self.assertEqual(plan["actions"][0]["needs_approval"], step != "friendly")

    def test_highest_only_when_lower_already_sent(self):
        plan = build_plan(
            [inv(id="INV-H", due_date="2026-09-30")],
            [{"invoice_id": "INV-H", "step": "friendly", "sent_on": "2026-10-03"}],
            "2026-10-12",
        )
        self.assertEqual(plan["actions"][0]["step"], "firm")

    def test_already_covered_by_same_or_higher(self):
        plan = build_plan(
            [inv(id="INV-C", due_date="2026-09-01")],
            [
                {"invoice_id": "INV-C", "step": "friendly", "sent_on": "2026-09-04"},
                {"invoice_id": "INV-C", "step": "firm", "sent_on": "2026-09-11"},
                {"invoice_id": "INV-C", "step": "final", "sent_on": "2026-09-25"},
            ],
            "2026-10-12",
        )
        self.assertEqual(plan["actions"], [])

    def test_ignores_invalid_sent_entries(self):
        plan = build_plan(
            [inv(id="INV-S", due_date="2026-10-09")],
            [
                {"invoice_id": "UNKNOWN", "step": "friendly", "sent_on": "2026-10-01"},
                {"invoice_id": "INV-S", "step": "nag", "sent_on": "2026-10-01"},
                {"invoice_id": "INV-S", "step": "friendly", "sent_on": "2099-01-01"},
            ],
            "2026-10-12",
        )
        self.assertEqual(plan["actions"], [])

    def test_lexicographic_sort(self):
        plan = build_plan(
            [
                inv(id="INV-99", due_date="2026-09-01"),
                inv(id="INV-100", due_date="2026-09-01"),
            ],
            [],
            "2026-10-12",
        )
        ids = [a["invoice_id"] for a in plan["actions"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(ids[0], "INV-100")


class MessageTest(unittest.TestCase):
    def test_message_contains_required_fields_only(self):
        msg = format_message("friendly", "Acme", "INV-1", "2026-09-30", "EUR", 1250.0, 12)
        for needle in ("Acme", "INV-1", "2026-09-30", "EUR 1250.00", "12"):
            self.assertIn(needle, msg)
        for banned in ("fee", "interest", "EUR 40", "25 EUR", "reminder we sent"):
            self.assertNotIn(banned.lower(), msg.lower())


class SampleFixtureTest(unittest.TestCase):
    def test_sample_data_for_2026_10_12(self):
        invoices = json.loads((DATA_DIR / "invoices.json").read_text(encoding="utf-8"))
        sent = json.loads((DATA_DIR / "sent.json").read_text(encoding="utf-8"))
        plan = build_plan(invoices, sent, "2026-10-12")

        actions = [(a["invoice_id"], a["step"], a["days_overdue"], a["needs_approval"]) for a in plan["actions"]]
        self.assertEqual(
            actions,
            [
                ("INV-1001", "firm", 12, True),
                ("INV-1002", "friendly", 3, False),
                ("INV-1004", "final", 32, True),
                ("INV-1009", "firm", 12, True),
                ("INV-1011", "firm", 10, True),
            ],
        )
        skipped = [(s["invoice_id"], s["reason"]) for s in plan["skipped"]]
        self.assertEqual(
            skipped,
            [
                ("INV-1007", "invalid_due_date"),
                ("INV-1008", "missing_due_date"),
                ("INV-1010", "duplicate_id"),
            ],
        )
        for action in plan["actions"]:
            self.assertIn(action["invoice_id"], action["message"])
            self.assertIn(str(action["days_overdue"]), action["message"])


class CliSmokeTest(unittest.TestCase):
    def test_bad_today_exits_nonzero(self):
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "plan.py",
                "--invoices",
                str(DATA_DIR / "invoices.json"),
                "--sent",
                str(DATA_DIR / "sent.json"),
                "--today",
                "not-a-date",
                "--out",
                "/tmp/dynarq-actions-test.json",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("today", result.stderr.lower())

    def test_missing_file_exits_nonzero(self):
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "plan.py",
                "--invoices",
                "missing.json",
                "--sent",
                str(DATA_DIR / "sent.json"),
                "--today",
                "2026-10-12",
                "--out",
                "/tmp/dynarq-actions-test.json",
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
