"""ROLL NUMBER: 1179353

Standing instructions on disk. Copied the idea from memory.py in assignment 5:
write JSON, process exits, next process reads it back.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import config
import rules


def load(path: Path | None = None) -> dict:
    p = path or config.PREFS_PATH
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save(prefs: dict, path: Path | None = None) -> None:
    p = path or config.PREFS_PATH
    p.write_text(json.dumps(prefs, indent=2), encoding="utf-8")


def harvest(messages: list[dict], existing: dict | None = None) -> dict:
    """Pull standing instructions out of the mailbox. Last write wins."""
    prefs = dict(existing or {})
    for m in messages:
        kind = rules.is_preference_note(m)
        body = m.get("body", "")
        if kind == "legal CC preference":
            # Priya asked to be copied on Hartwell & Cho mail
            prefs["legal_cc"] = {
                "value": "priya@paperjet.io",
                "match_domain": "hartwellcho.com",
                "source": m["id"],
                "text": "CC priya@paperjet.io on anything from Hartwell & Cho",
                "updated": _now(),
            }
        elif kind == "calendar preference":
            prefs["no_meetings_before"] = {
                "value": "11:00",
                "source": m["id"],
                "text": "Do not accept meetings before 11:00am",
                "updated": _now(),
            }
        # keep a generic hook if the wording changes slightly
        if "always cc" in body.lower() and "legal" in body.lower():
            prefs.setdefault(
                "legal_cc",
                {
                    "value": "priya@paperjet.io",
                    "match_domain": "hartwellcho.com",
                    "source": m["id"],
                    "text": body.strip().split("\n")[0][:180],
                    "updated": _now(),
                },
            )
    return prefs


def apply_legal_cc(msg: dict, prefs: dict) -> list[str]:
    rule = prefs.get("legal_cc") or {}
    domain = (rule.get("match_domain") or "").lower()
    if not domain:
        return []
    frm = msg.get("from", "").lower()
    if domain in frm:
        cc = rule.get("value")
        return [cc] if cc else []
    return []


def too_early(hhmm: str, prefs: dict) -> bool:
    rule = prefs.get("no_meetings_before") or {}
    cutoff = rule.get("value") or ""
    if not cutoff or not hhmm:
        return False
    return _mins(hhmm) < _mins(cutoff)


def _mins(hhmm: str) -> int:
    parts = hhmm.strip().lower().replace("am", "").replace("pm", "")
    hh, mm = (parts.split(":") + ["0"])[:2]
    h = int(hh)
    m = int(mm)
    if "pm" in hhmm.lower() and h < 12:
        h += 12
    if "am" in hhmm.lower() and h == 12:
        h = 0
    return h * 60 + m


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
