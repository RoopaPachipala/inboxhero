"""ROLL NUMBER: 1179353

Append-only jsonl log. Each event is one line so a marker can grep cap=R1.
"""

import json
from datetime import datetime, timezone

import config


def reset() -> None:
    if config.TRACE_PATH.exists():
        config.TRACE_PATH.unlink()


def log(cap: str, event: str, **payload) -> dict:
    row = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cap": cap,
        "event": event,
        **payload,
    }
    with config.TRACE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")
    return row
