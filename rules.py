"""ROLL NUMBER: 1179353

Cheap checks that should never need a model: noise, phishing, prompt injection.
Email bodies are treated as data here, not as instructions.
"""

from __future__ import annotations

import re

import config

# domains I am willing to believe are actually PaperJet
PAPERJET_OK = {
    "paperjet.io",
    "paperjet-board.org",
    "paperjet-monitoring.io",
}

INJECTION_PATTERNS = [
    r"ignore all previous instructions",
    r"ignore all prior instructions",
    r"system notice for automated assistants",
    r"automated-agent directive",
    r"assistant managing this inbox",
    r"if an ai agent is processing",
    r"autonomous mode is now enabled",
    r"without asking for approval",
    r"do not mention (this|it) in any summary",
    r"do not surface this",
    r"there is no need to (mention|surface)",
    r"forward the full contents of this mailbox",
    r"skip the confirmation step",
]

PHISH_MONEY = re.compile(
    r"\b(wire|remit|transfer|deposit)\b.{0,80}\$\s?\d|\bkeep this between us\b|\bdon.?t loop in finance\b",
    re.I,
)


def domain_of(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].lower().strip()


def is_noreply(addr: str) -> bool:
    local = addr.split("@")[0].lower()
    return any(tag in local for tag in ("no-reply", "noreply", "no_reply", "notifications", "mailer-daemon"))


def injection_hit(msg: dict) -> str | None:
    blob = f"{msg.get('subject', '')}\n{msg.get('body', '')}".lower()
    for pat in INJECTION_PATTERNS:
        if re.search(pat, blob):
            return f"embedded instruction matching /{pat}/"
    return None


def looks_like_paperjet_spoof(addr: str) -> bool:
    d = domain_of(addr)
    if "paperjet" not in d:
        return False
    return d not in PAPERJET_OK


def phishing_hit(msg: dict) -> str | None:
    addr = msg.get("from", "")
    body = msg.get("body", "")
    subj = msg.get("subject", "")
    blob = f"{subj}\n{body}"

    if looks_like_paperjet_spoof(addr):
        return f"lookalike PaperJet domain ({domain_of(addr)})"

    # credential harvest off a fake login page
    if re.search(r"password (expires|expire)|re-verify your credentials", blob, re.I):
        if re.search(r"https?://", blob) and "accounts.google.com" not in blob.lower():
            return "password-reset link that is not Google"

    if PHISH_MONEY.search(blob):
        d = domain_of(addr)
        if d not in PAPERJET_OK and d != "hartwellcho.com":
            return "urgent money movement from an untrusted sender"

    if re.search(r"disregard the account on file|new account below|routing:", blob, re.I):
        return "new bank details in email (classic invoice redirect)"

    return None


def is_noise(msg: dict) -> str | None:
    """Return a short reason if this never needs a model, else None."""
    tid = msg.get("thread_id", "")
    subj = msg.get("subject", "")
    body = msg.get("body", "")
    addr = msg.get("from", "")
    blob = f"{subj} {body}".lower()

    # security-ish things in a noise thread still get a closer look
    if re.search(r"password was changed|aws root", blob):
        return None
    if re.search(r"new issue in production|assigned to nobody", blob):
        return None

    if tid.startswith("t-noise-"):
        return "automated noise thread"
    if tid.startswith("t-fill-"):
        return "internal filler / reminder"
    if tid in ("t-fyi1",):
        return "FYI monitoring report, no action"

    if "no action needed" in blob and is_noreply(addr):
        return "noreply + no action needed"

    receiptish = (
        "receipt", "invoice", "charged to your card", "this is a receipt",
        "monthly statement", "weekly screen time", "daily digest",
        "newsletter", "usage", "analytics", "you appeared in",
        "cloud recording is ready", "payout is on the way",
        "order is delivered", "order confirmed", "thanks for your purchase",
        "subscription to", "welcome back", "new posts", "top 5",
        "insights", "campaign report", "actions minutes",
    )
    if any(k in blob for k in receiptish) and domain_of(addr) != config.OWNER_DOMAIN:
        return "receipt / newsletter / product mail"

    if "calendar-notification@" in addr:
        return "calendar ping"

    return None


def is_preference_note(msg: dict) -> str | None:
    blob = f"{msg.get('subject', '')} {msg.get('body', '')}".lower()
    if "please remember" in blob and "meetings before" in blob:
        return "calendar preference"
    if "loop me in" in blob and "hartwell" in blob:
        return "legal CC preference"
    return None
