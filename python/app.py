"""Owner page for today's payment reminders.

Run from inside python/:

    python app.py

Environment variables:
    PORT      port to listen on, default 8000
    DATA_DIR  folder with invoices.json and sent.json, default ../data
    TODAY     date as YYYY-MM-DD, default the real date
"""

from __future__ import annotations

import json
import os
from datetime import date
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from plan import build_plan, format_amount, parse_iso_date

PORT = int(os.environ.get("PORT", "8000"))
DATA_DIR = os.environ.get("DATA_DIR", "../data")
TODAY = os.environ.get("TODAY") or date.today().isoformat()

DECISIONS: dict[tuple[str, str], str] = {}

SKIP_LABELS = {
    "duplicate_id": "duplicate invoice id",
    "invalid_amount": "invalid amount",
    "missing_due_date": "missing due date",
    "invalid_due_date": "invalid due date",
    "invalid_paid_date": "invalid paid date",
}

CSS = """
:root {
  --ink: #1a1a1a;
  --muted: #5c5c5c;
  --line: #d8d8d8;
  --bg: #f7f6f3;
  --card: #ffffff;
  --accent: #0f4c5c;
  --ok: #1b6b3a;
  --no: #8a2f2f;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  color: var(--ink);
  background: var(--bg);
  line-height: 1.45;
}
header {
  padding: 1.5rem 1.25rem 1rem;
  border-bottom: 1px solid var(--line);
  background: var(--card);
}
header h1 {
  margin: 0 0 0.25rem;
  font-size: 1.6rem;
  font-weight: 600;
  letter-spacing: -0.02em;
}
header p { margin: 0; color: var(--muted); font-size: 0.95rem; }
main { padding: 1.25rem; max-width: 52rem; margin: 0 auto; }
h2 {
  margin: 1.75rem 0 0.75rem;
  font-size: 1.15rem;
  font-weight: 600;
}
.banner {
  padding: 0.9rem 1rem;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 4px;
}
.item {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 1rem;
  margin: 0 0 0.75rem;
}
.meta {
  display: grid;
  gap: 0.35rem 1.25rem;
  grid-template-columns: 1fr;
  margin: 0 0 0.75rem;
  font-size: 0.95rem;
}
@media (min-width: 560px) {
  .meta { grid-template-columns: 1fr 1fr; }
}
.meta dt { color: var(--muted); font-size: 0.8rem; margin: 0; }
.meta dd { margin: 0 0 0.4rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.9rem; }
.step {
  display: inline-block;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--accent);
  border: 1px solid var(--accent);
  padding: 0.15rem 0.4rem;
  border-radius: 3px;
}
.message {
  white-space: pre-wrap;
  background: var(--bg);
  border-left: 3px solid var(--accent);
  padding: 0.75rem 0.9rem;
  margin: 0.75rem 0;
  font-size: 0.92rem;
}
.actions { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
button {
  font: inherit;
  cursor: pointer;
  border-radius: 3px;
  border: 1px solid var(--ink);
  background: var(--ink);
  color: #fff;
  padding: 0.45rem 0.9rem;
}
button.secondary {
  background: transparent;
  color: var(--ink);
}
button:focus-visible, a:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.status-ok { color: var(--ok); font-weight: 600; }
.status-no { color: var(--no); font-weight: 600; }
ul.skipped { padding-left: 1.1rem; margin: 0; }
ul.skipped li { margin: 0.35rem 0; }
.error { border-color: var(--no); color: var(--no); }
"""


def load_json(name: str):
    path = os.path.join(DATA_DIR, name)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def invoice_index(invoices: list) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for inv in invoices:
        if isinstance(inv, dict) and isinstance(inv.get("id"), str):
            out[inv["id"]] = inv
    return out


def render_page(body_inner: str, title: str = "Payment reminders") -> bytes:
    html = (
        "<!doctype html><html lang=\"en\"><head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(title)}</title>"
        f"<style>{CSS}</style>"
        "</head><body>"
        f"{body_inner}"
        "</body></html>"
    )
    return html.encode("utf-8")


def page_shell(content: str) -> str:
    return (
        "<header>"
        "<h1>Payment reminders</h1>"
        f"<p>Today · {escape(TODAY)}</p>"
        "</header>"
        f"<main>{content}</main>"
    )


def render_action(action: dict, inv: dict | None) -> str:
    invoice_id = action["invoice_id"]
    step = action["step"]
    customer = inv.get("customer", "—") if inv else "—"
    currency = inv.get("currency", "") if inv else ""
    amount = inv.get("amount") if inv else None
    amount_text = (
        format_amount(currency, float(amount))
        if isinstance(amount, (int, float)) and not isinstance(amount, bool)
        else "—"
    )
    decision = DECISIONS.get((invoice_id, step))

    parts = [
        '<article class="item">',
        '<dl class="meta">',
        f"<div><dt>Customer</dt><dd>{escape(str(customer))}</dd></div>",
        f"<div><dt>Invoice</dt><dd>{escape(invoice_id)}</dd></div>",
        f"<div><dt>Amount</dt><dd>{escape(amount_text)}</dd></div>",
        f"<div><dt>Days overdue</dt><dd>{action['days_overdue']}</dd></div>",
        f"<div><dt>Step</dt><dd><span class=\"step\">{escape(step)}</span></dd></div>",
        "</dl>",
        f"<div class=\"message\">{escape(action['message'])}</div>",
    ]

    if action.get("needs_approval"):
        if decision == "approved":
            parts.append('<p class="status-ok">Approved</p>')
        elif decision == "rejected":
            parts.append('<p class="status-no">Rejected</p>')
        else:
            parts.append('<div class="actions">')
            for label, value in (("Approve", "approved"), ("Reject", "rejected")):
                cls = "" if value == "approved" else ' class="secondary"'
                parts.append(
                    f'<form method="post" action="/decision" style="display:inline">'
                    f'<input type="hidden" name="invoice_id" value="{escape(invoice_id, quote=True)}">'
                    f'<input type="hidden" name="step" value="{escape(step, quote=True)}">'
                    f'<input type="hidden" name="decision" value="{value}">'
                    f'<button type="submit"{cls}>{label}</button>'
                    f"</form>"
                )
            parts.append("</div>")
    else:
        parts.append("<p>No approval needed · ready to send</p>")

    parts.append("</article>")
    return "".join(parts)


def build_home() -> bytes:
    if parse_iso_date(TODAY) is None:
        content = (
            '<p class="banner error">TODAY must be a real date in YYYY-MM-DD form '
            f"(got {escape(TODAY)}).</p>"
        )
        return render_page(page_shell(content))

    try:
        invoices = load_json("invoices.json")
        sent = load_json("sent.json")
    except (OSError, json.JSONDecodeError) as exc:
        content = (
            '<p class="banner error">Could not read invoice data: '
            f"{escape(str(exc))}</p>"
        )
        return render_page(page_shell(content))

    if not isinstance(invoices, list) or not isinstance(sent, list):
        content = '<p class="banner error">Invoice files must contain JSON arrays.</p>'
        return render_page(page_shell(content))

    plan = build_plan(invoices, sent, TODAY)
    by_id = invoice_index(invoices)
    sections: list[str] = []

    sections.append("<h2>Today's plan</h2>")
    if not plan["actions"]:
        sections.append('<p class="banner">Nothing to do today.</p>')
    else:
        for action in plan["actions"]:
            sections.append(render_action(action, by_id.get(action["invoice_id"])))

    sections.append("<h2>Skipped invoices</h2>")
    if not plan["skipped"]:
        sections.append('<p class="banner">No invoices were skipped.</p>')
    else:
        sections.append('<ul class="skipped">')
        for item in plan["skipped"]:
            reason = SKIP_LABELS.get(item["reason"], item["reason"].replace("_", " "))
            sections.append(
                f"<li><strong>{escape(item['invoice_id'])}</strong> — {escape(reason)}</li>"
            )
        sections.append("</ul>")

    return render_page(page_shell("".join(sections)))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?", 1)[0] != "/":
            self.send_error(404)
            return
        data = build_home()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/decision":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        form = parse_qs(raw)
        invoice_id = (form.get("invoice_id") or [""])[0]
        step = (form.get("step") or [""])[0]
        decision = (form.get("decision") or [""])[0]
        if invoice_id and step in ("firm", "final") and decision in ("approved", "rejected"):
            DECISIONS[(invoice_id, step)] = decision
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("", PORT), Handler)
    print(f"Serving on http://localhost:{PORT}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
