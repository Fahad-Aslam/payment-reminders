# Payment reminders

Python rules engine and owner page for planning late-payment reminders.

## Run

```bash
cd python
python3 -m unittest
python3 plan.py --invoices ../data/invoices.json --sent ../data/sent.json \
  --today 2026-10-12 --out ../actions.json
TODAY=2026-10-12 python3 app.py
```

Open `http://localhost:8000/`. Optional env: `PORT`, `DATA_DIR`, `TODAY`.

## Decisions

- Python only (stdlib); TypeScript starter removed.
- One `build_plan` shared by the CLI and the page; no duplicated rules.
- Reminder text from fixed templates so the tool works fully offline.
- Firm/final approvals are in-memory for the process lifetime only.

## Next

Persist approvals, record sent reminders back into `sent.json`, and wire a real send path after legal wording is confirmed.
