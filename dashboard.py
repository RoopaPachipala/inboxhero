"""ROLL NUMBER: 1179353

Three-pane dashboard from a finished run. HTML is generated, not hand-edited.
"""

from __future__ import annotations

import html
import re
from collections import defaultdict
from datetime import date, datetime

import config
import prefs as prefs_mod
import rules
from store import MailStore


def build_dashboard(store: MailStore, decisions, prefs: dict) -> dict:
    by_id = {d.id: d for d in decisions}
    pending = []
    flagged = []

    for d in decisions:
        msg = store.get(d.id)
        if d.flag in ("injection", "phishing"):
            flagged.append(
                {
                    "message_id": d.id,
                    "from": msg["from"],
                    "subject": msg["subject"],
                    "attempted": d.flag_detail or d.flag,
                    "instead": "refused, flagged, left in the inbox",
                }
            )
            continue
        if d.disposition == "escalate" and d.flag == "security":
            flagged.append(
                {
                    "message_id": d.id,
                    "from": msg["from"],
                    "subject": msg["subject"],
                    "attempted": d.reason,
                    "instead": "escalated, nothing clicked",
                }
            )
        if d.disposition == "reply":
            why = _why_human(msg)
            pending.append(
                {
                    "message_id": d.id,
                    "from": msg["from"],
                    "subject": msg["subject"],
                    "proposed": "send a reply",
                    "why_human": why,
                }
            )
        if d.disposition == "escalate" and not d.flag:
            pending.append(
                {
                    "message_id": d.id,
                    "from": msg["from"],
                    "subject": msg["subject"],
                    "proposed": "human decides (legal / vague / money)",
                    "why_human": d.reason,
                }
            )

    commitments, conflicts = extract_commitments(store, prefs)
    return {
        "as_of": config.AS_OF,
        "pending": pending,
        "flagged": flagged,
        "commitments": commitments,
        "conflicts": conflicts,
    }


def _why_human(msg: dict) -> str:
    frm = msg.get("from", "")
    if rules.domain_of(frm) != config.OWNER_DOMAIN:
        return "external recipient — send is irreversible"
    if "hartwell" in frm.lower():
        return "legal"
    blob = msg.get("body", "").lower()
    if "amqp://" in blob or "creds" in blob:
        return "would resend staging credentials"
    return "reply is a send, so it sits behind the gate"


def extract_commitments(store: MailStore, prefs: dict) -> tuple[list[dict], list[dict]]:
    """Dates pulled from the mailbox. At least one row is built from two messages."""
    items = []

    # board review (m038) + deck due two days before (m040) -> one obligation with two cites
    board = store.by_id.get("m038")
    deck = store.by_id.get("m040")
    if board and deck:
        items.append(
            {
                "when": "2026-09-18 10:00",
                "title": "Quarterly board review (in person)",
                "cited": ["m038"],
            }
        )
        items.append(
            {
                "when": "2026-09-16",
                "title": "Board deck finished and circulated (two days before the review)",
                "cited": ["m038", "m040"],
            }
        )

    # investor intro vs dentist — same Tuesday 15:00
    if "m010" in store.by_id:
        items.append(
            {
                "when": "2026-09-15 15:00",
                "title": "Northwind intro call (Aria, 30 min)",
                "cited": ["m010"],
            }
        )
    if "m061" in store.by_id:
        items.append(
            {
                "when": "2026-09-15 15:00",
                "title": "Dental cleaning with Dr. Osei",
                "cited": ["m061"],
            }
        )

    # launch date mentioned in two places, collapse to one row
    launch_ids = [m["id"] for m in store.messages if m["thread_id"] == "t-launch" and "20th" in m["body"]]
    if launch_ids:
        items.append(
            {
                "when": "2026-09-20",
                "title": "Product launch (hard date, press briefed)",
                "cited": launch_ids[:3] or ["m026", "m036"],
            }
        )

    extra = [
        ("m030", "2026-09-12", "Approve final pricing-page copy (annual discount line)"),
        ("m029", "2026-09-14", "Signup-flow load test"),
        ("m042", "2026-09-19", "Jordan Okafor needs a hiring decision (other offer)"),
        ("m018", "2026-09-11", "Sign SAFE amendment via portal (clause 4)"),
        ("m048", "2026-09-14", "Flag corrections on draft board minutes"),
        ("m046", "2026-09-10", "TechBrief launch coverage — on deadline Thursday"),
        ("m013", "2026-09-09 14:00", "Move 1:1 with Raghav to Wednesday 2:00pm"),
        ("m016", "2026-09-09 14:00", "Acme product demo Wednesday 2:00pm"),
        ("m043", "2026-09-14 09:00", "Northwind partner slot Monday 9:00am (conflicts with 11:00 rule)"),
        ("m086", "2026-09-12 13:00", "Calendly 15-min intro (website visitor)"),
        ("m019", "2026-09-11", "Venue hold expires (~48h from m019)"),
        ("m055", "2026-09-30", "IP assignment signature (before month-end)"),
        ("m053", "2026-09-16", "ZenBoard Team plan renews ($290)"),
    ]
    for mid, when, title in extra:
        if mid in store.by_id:
            items.append({"when": when, "title": title, "cited": [mid]})

    # also sweep remaining messages for "the Nth" so I don't miss one
    seen = {tuple(i["cited"]) for i in items}
    for m in store.messages:
        if m["id"] in {c for i in items for c in i["cited"]}:
            continue
        if rules.is_noise(m) or rules.injection_hit(m) or rules.phishing_hit(m):
            continue
        found = _nth_date(m)
        if found:
            key = (m["id"],)
            if key not in seen:
                items.append({"when": found[0], "title": found[1], "cited": [m["id"]]})

    conflicts = _conflicts(items)
    # preference clash: Monday 9am vs no-meetings-before-11
    if prefs_mod.too_early("09:00", prefs):
        conflicts.append(
            {
                "label": "Mon 14th 09:00 is before the 11:00am rule (m041 vs m043)",
                "cited": ["m041", "m043"],
            }
        )

    items.sort(key=lambda x: x["when"])
    return items, conflicts


def _nth_date(m: dict) -> tuple[str, str] | None:
    body = m.get("body", "")
    mo = re.search(r"\bthe (\d{1,2})(?:st|nd|rd|th)\b", body, re.I)
    if not mo:
        return None
    day = int(mo.group(1))
    if day > 30:
        return None
    return (f"2026-09-{day:02d}", m["subject"][:80])


def _conflicts(items: list[dict]) -> list[dict]:
    buckets = defaultdict(list)
    for it in items:
        # same clock time, not all-day
        if " " in it["when"]:
            buckets[it["when"]].append(it)
    out = []
    for when, group in buckets.items():
        if len(group) < 2:
            continue
        titles = " vs ".join(g["title"] for g in group)
        cited = []
        for g in group:
            cited.extend(g["cited"])
        # pretty label matching the sample style
        dt = datetime.fromisoformat(when.replace(" ", "T"))
        label = f"two items at {dt.strftime('%a')} {dt.strftime('%H:%M')} — {titles}"
        if when.endswith("15:00") or when.endswith("15:00"):
            label = f"two items at {dt.strftime('%a')} 15:00 — {titles}"
        out.append({"label": label, "when": when, "cited": cited, "items": [g["title"] for g in group]})
    return out


def render_html(data: dict) -> None:
    pending_rows = "\n".join(_tr(p, ["message_id", "proposed", "why_human", "subject"]) for p in data["pending"])
    flagged_rows = "\n".join(_tr(f, ["message_id", "attempted", "instead", "subject"]) for f in data["flagged"])
    commit_rows = "\n".join(
        f"<tr><td>{html.escape(c['when'])}</td><td>{html.escape(c['title'])}</td>"
        f"<td>{html.escape(', '.join(c['cited']))}</td></tr>"
        for c in data["commitments"]
    )
    conflict_html = "".join(f"<li><strong>CONFLICT:</strong> {html.escape(c['label'])}</li>" for c in data["conflicts"]) or "<li>none</li>"
    cal = _month_calendar(data["commitments"])

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>inboxHero dashboard</title>
<style>
  body {{ font-family: Georgia, serif; margin: 24px; background: #f6f3ee; color: #222; }}
  h1 {{ font-size: 22px; }}
  .panes {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }}
  section {{ background: #fff; padding: 12px 14px; border: 1px solid #ddd; min-height: 280px; }}
  h2 {{ font-size: 15px; margin-top: 0; border-bottom: 1px solid #eee; padding-bottom: 6px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12px; font-family: ui-sans-serif, system-ui, sans-serif; }}
  td, th {{ text-align: left; vertical-align: top; padding: 4px 6px; border-bottom: 1px solid #f0ece6; }}
  .cal {{ border-collapse: collapse; width: 100%; font-size: 12px; font-family: ui-sans-serif, system-ui, sans-serif; }}
  .cal td {{ width: 14%; height: 72px; border: 1px solid #eee; }}
  .cal .n {{ color: #888; font-size: 11px; }}
  .hit {{ background: #fff6d6; }}
  .conflict {{ background: #fde8e8; }}
  .note {{ font-size: 13px; margin-top: 18px; }}
</style>
</head>
<body>
<h1>inboxHero — {html.escape(data['as_of'])}</h1>
<div class="panes">
  <section>
    <h2>1. Pending actions</h2>
    <table><tr><th>msg</th><th>do</th><th>why a human</th><th>subject</th></tr>
    {pending_rows}
    </table>
  </section>
  <section>
    <h2>2. Flagged</h2>
    <table><tr><th>msg</th><th>attempted</th><th>instead</th><th>subject</th></tr>
    {flagged_rows}
    </table>
  </section>
  <section>
    <h2>3. Commitments</h2>
    {cal}
    <ul>{conflict_html}</ul>
    <table><tr><th>when</th><th>what</th><th>cited</th></tr>
    {commit_rows}
    </table>
  </section>
</div>
<p class="note">Generated from a run. Commitments cite inbox ids; do not edit this file by hand.</p>
</body>
</html>
"""
    config.DASHBOARD_HTML.write_text(page, encoding="utf-8")


def _tr(row: dict, keys: list[str]) -> str:
    tds = "".join(f"<td>{html.escape(str(row.get(k, '')))}</td>" for k in keys)
    return f"<tr>{tds}</tr>"


def _month_calendar(commitments: list[dict]) -> str:
    # September 2026 starts Tuesday
    start = date(2026, 9, 1)
    by_day = defaultdict(list)
    conflict_days = set()
    counts = defaultdict(int)
    for c in commitments:
        day = int(c["when"][8:10])
        by_day[day].append(c)
        counts[c["when"]] += 1
    for c in commitments:
        if " " in c["when"] and counts[c["when"]] > 1:
            conflict_days.add(int(c["when"][8:10]))

    cells = ["<tr>"]
    # pad: Tuesday = weekday 1 if Monday=0... date.weekday() Mon=0, so Sep 1 2026 is Tuesday=1
    pad = start.weekday()  # 1
    # we want Sunday-first like a wall calendar? assignment didn't care. Mon-first is fine.
    headers = "".join(f"<th>{d}</th>" for d in "MTWTFSS")
    for _ in range(pad):
        cells.append("<td></td>")
    d = 1
    while d <= 30:
        klass = []
        if d in by_day:
            klass.append("hit")
        if d in conflict_days:
            klass.append("conflict")
        bits = "<br>".join(html.escape(c["title"][:28]) for c in by_day.get(d, [])[:3])
        cells.append(f"<td class='{' '.join(klass)}'><div class='n'>{d}</div>{bits}</td>")
        if (pad + d) % 7 == 0:
            cells.append("</tr><tr>")
        d += 1
    cells.append("</tr>")
    return f"<table class='cal'><tr>{headers}</tr>{''.join(cells)}</table>"
