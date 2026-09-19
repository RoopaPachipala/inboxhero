"""ROLL NUMBER: 1179353

The only two functions that can actually send or delete. Everything else
has to come through here. Dry-run logs the proposal and returns False.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import config
import trace


def require_approval(
    cap: str,
    action: str,
    summary: str,
    *,
    dry_run: bool,
    auto_approve: bool,
    message_id: str | None = None,
) -> bool:
    """Return True only if the irreversible action may proceed."""
    proposed = {"action": action, "summary": summary, "message_id": message_id}

    if dry_run:
        trace.log(cap, "gate", **proposed, decision="dry-run")
        print(f"  [dry-run] would {action}: {summary}")
        return False

    if auto_approve or config.AUTO_APPROVE:
        trace.log(cap, "gate", **proposed, decision="approved-auto")
        print(f"  [auto] {action}: {summary}")
        return True

    try:
        ans = input(f"Approve {action}? {summary}  [y/N] ").strip().lower()
    except EOFError:
        ans = "n"
    ok = ans in ("y", "yes")
    trace.log(cap, "gate", **proposed, decision="approved" if ok else "denied")
    return ok


def send(
    cap: str,
    *,
    source_id: str,
    to: str,
    subject: str,
    body: str,
    cc: list[str] | None = None,
    dry_run: bool,
    auto_approve: bool,
) -> Path | None:
    cc = cc or []
    summary = f"send to {to} subj={subject!r}"
    if not require_approval(
        cap, "send", summary, dry_run=dry_run, auto_approve=auto_approve, message_id=source_id
    ):
        return None

    config.OUTBOX_DIR.mkdir(exist_ok=True)
    path = config.OUTBOX_DIR / f"{source_id}.txt"
    lines = [
        f"From: {config.OWNER}",
        f"To: {to}",
        f"Cc: {', '.join(cc)}" if cc else "Cc:",
        f"Subject: {subject}",
        f"In-Reply-To: {source_id}",
        f"Date: {datetime.now().isoformat(timespec='seconds')}",
        "",
        body.strip(),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    trace.log(cap, "send", message_id=source_id, path=str(path), to=to, cc=cc)
    return path


def delete(
    cap: str,
    message_id: str,
    *,
    dry_run: bool,
    auto_approve: bool,
) -> bool:
    # I never call this from the pipeline. It exists so the gate can be shown,
    # and so an injection that says "delete this" still has to get through it.
    summary = f"delete {message_id}"
    if not require_approval(
        cap, "delete", summary, dry_run=dry_run, auto_approve=auto_approve, message_id=message_id
    ):
        return False
    trace.log(cap, "delete", message_id=message_id, note="mock store has no trash; refused to actually drop mail")
    # still don't drop it from inbox.json. deleting in this mock is a lie.
    return False
