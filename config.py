"""ROLL NUMBER: 1179353

Env loading. Nothing else should read os.environ directly.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Frozen on purpose: the inbox only covers 2-9 Sep, so I treat the morning
# of the 10th as "now". Otherwise a marker running this in late September
# would see every deadline as already missed.
AS_OF = os.getenv("INBOXHERO_AS_OF", "2026-09-10")

OWNER = "sam@paperjet.io"
OWNER_DOMAIN = "paperjet.io"

AUTO_APPROVE = os.getenv("INBOXHERO_AUTO_APPROVE", "0").strip() in ("1", "true", "yes")

INBOX_PATH = ROOT / "inbox.json"
OUTBOX_DIR = ROOT / "outbox"
TRACE_PATH = ROOT / "trace.jsonl"
PREFS_PATH = ROOT / "prefs.json"
DECISIONS_PATH = ROOT / "decisions.json"
DASHBOARD_HTML = ROOT / "dashboard.html"
DASHBOARD_JSON = ROOT / "dashboard.json"


def has_llm() -> bool:
    return bool(API_KEY)
