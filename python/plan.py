"""Payment reminder rules engine.

Run from inside python/:

    python plan.py --invoices ../data/invoices.json --sent ../data/sent.json \\
        --today 2026-10-12 --out ../actions.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from typing import Any

STEPS = ("friendly", "firm", "final")
STEP_DAYS = {"friendly": 3, "firm": 10, "final": 24}
HIGHER = {
    "friendly": ("friendly", "firm", "final"),
    "firm": ("firm", "final"),
    "final": ("final",),
}


def parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def days_overdue(due: date, today: date) -> int:
    return (today - due).days


def highest_step(days: int) -> str | None:
    step = None
    for name in STEPS:
        if days >= STEP_DAYS[name]:
            step = name
    return step


def find_duplicate_ids(invoices: list) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for inv in invoices:
        if not isinstance(inv, dict):
            continue
        inv_id = inv.get("id")
        if not isinstance(inv_id, str):
            continue
        if inv_id in seen:
            duplicates.add(inv_id)
        else:
            seen.add(inv_id)
    return duplicates


def bad_data_reason(inv: dict, today: date, duplicates: set[str]) -> str | None:
    inv_id = inv.get("id")
    if isinstance(inv_id, str) and inv_id in duplicates:
        return "duplicate_id"

    amount = inv.get("amount")
    if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:
        return "invalid_amount"

    due_raw = inv.get("due_date", None)
    if due_raw is None or due_raw == "":
        return "missing_due_date"
    due = parse_iso_date(due_raw)
    if due is None:
        return "invalid_due_date"

    paid_raw = inv.get("paid_date", None)
    if paid_raw is not None:
        paid = parse_iso_date(paid_raw)
        if paid is None or paid > today:
            return "invalid_paid_date"

    return None


def index_sent(sent: list, known_ids: set[str]) -> dict[str, set[str]]:
    indexed: dict[str, set[str]] = {}
    for entry in sent:
        if not isinstance(entry, dict):
            continue
        invoice_id = entry.get("invoice_id")
        step = entry.get("step")
        if invoice_id not in known_ids or step not in STEPS:
            continue
        indexed.setdefault(invoice_id, set()).add(step)
    return indexed


def already_covered(sent_steps: set[str], step: str) -> bool:
    return any(s in sent_steps for s in HIGHER[step])


def format_amount(currency: str, amount: float) -> str:
    return f"{currency} {amount:.2f}"


def format_message(
    step: str,
    customer: str,
    invoice_id: str,
    due_date: str,
    currency: str,
    amount: float,
    days: int,
) -> str:
    money = format_amount(currency, amount)
    if step == "friendly":
        return (
            f"Hello {customer},\n\n"
            f"This is a friendly reminder that invoice {invoice_id} for {money}, "
            f"due on {due_date}, is now {days} days overdue. "
            f"Please arrange payment when you can.\n\n"
            f"Thank you."
        )
    if step == "firm":
        return (
            f"Hello {customer},\n\n"
            f"Invoice {invoice_id} for {money} was due on {due_date} and is now "
            f"{days} days overdue. Please settle this invoice promptly.\n\n"
            f"Thank you."
        )
    return (
        f"Hello {customer},\n\n"
        f"Final notice: invoice {invoice_id} for {money}, due on {due_date}, "
        f"is {days} days overdue. Please pay the outstanding amount without delay.\n\n"
        f"Thank you."
    )


def build_plan(invoices: list, sent: list, today: str) -> dict:
    today_date = parse_iso_date(today)
    if today_date is None:
        raise ValueError(f"invalid today date: {today!r}")

    duplicates = find_duplicate_ids(invoices)
    known_ids = {
        inv["id"]
        for inv in invoices
        if isinstance(inv, dict) and isinstance(inv.get("id"), str)
    }
    sent_index = index_sent(sent, known_ids)

    actions: list[dict] = []
    skipped: list[dict] = []
    skipped_ids: set[str] = set()

    for inv in invoices:
        if not isinstance(inv, dict):
            continue
        inv_id = inv.get("id")
        if not isinstance(inv_id, str):
            continue

        reason = bad_data_reason(inv, today_date, duplicates)
        if reason is not None:
            if inv_id not in skipped_ids:
                skipped.append({"invoice_id": inv_id, "reason": reason})
                skipped_ids.add(inv_id)
            continue

        paid_raw = inv.get("paid_date", None)
        if paid_raw is not None:
            continue

        due = parse_iso_date(inv["due_date"])
        assert due is not None
        days = days_overdue(due, today_date)
        step = highest_step(days)
        if step is None:
            continue
        if already_covered(sent_index.get(inv_id, set()), step):
            continue

        currency = inv.get("currency", "")
        if not isinstance(currency, str):
            currency = ""
        amount = float(inv["amount"])
        customer = inv.get("customer", "")
        if not isinstance(customer, str):
            customer = ""

        actions.append(
            {
                "invoice_id": inv_id,
                "step": step,
                "needs_approval": step in ("firm", "final"),
                "days_overdue": days,
                "message": format_message(
                    step,
                    customer,
                    inv_id,
                    due.isoformat(),
                    currency,
                    amount,
                    days,
                ),
            }
        )

    actions.sort(key=lambda a: a["invoice_id"])
    skipped.sort(key=lambda s: s["invoice_id"])
    return {"today": today, "actions": actions, "skipped": skipped}


def read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan today's payment reminders.")
    parser.add_argument("--invoices", required=True, help="path to invoices.json")
    parser.add_argument("--sent", required=True, help="path to sent.json")
    parser.add_argument("--today", required=True, help="date as YYYY-MM-DD")
    parser.add_argument("--out", required=True, help="path to write the plan JSON")
    args = parser.parse_args()

    if parse_iso_date(args.today) is None:
        print(f"Error: --today must be a real date YYYY-MM-DD, got {args.today!r}", file=sys.stderr)
        sys.exit(1)

    try:
        invoices = read_json(args.invoices)
        sent = read_json(args.sent)
    except OSError as exc:
        print(f"Error: could not read input file: {exc}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(invoices, list) or not isinstance(sent, list):
        print("Error: invoices and sent must be JSON arrays", file=sys.stderr)
        sys.exit(1)

    plan = build_plan(invoices, sent, args.today)

    try:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2)
            f.write("\n")
    except OSError as exc:
        print(f"Error: could not write output file: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
