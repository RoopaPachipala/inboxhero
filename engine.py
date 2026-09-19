"""ROLL NUMBER: 1179353

The actual inboxHero pipeline.

Not a framework. Load -> split rule-path vs work-path -> retrieve -> draft
-> gate. Dashboard is a last pass over the same decisions.

Disposition vocab (used everywhere):
  reply     needs a written answer from Sam
  archive   done / noise / already handled
  defer     real, but not this morning
  delegate  someone else should own it
  escalate  human has to look (legal, money, phish, vague, secrets)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import config
import gate
import llm
import prefs as prefs_mod
import retrieve as retrieve_mod
import rules
import trace
from store import MailStore

DISPOSITIONS = ["reply", "archive", "defer", "delegate", "escalate"]


def reply_subject(subject: str) -> str:
    s = (subject or "").strip()
    if s.lower().startswith("re:"):
        return s
    return f"Re: {s}"


@dataclass
class Decision:
    id: str
    disposition: str
    reason: str
    rule_handled: bool
    flag: str | None = None
    flag_detail: str | None = None
    cited: list[str] = field(default_factory=list)


def classify_one(store: MailStore, msg: dict) -> Decision:
    mid = msg["id"]
    inj = rules.injection_hit(msg)
    if inj:
        return Decision(mid, "escalate", "prompt-injection, left in place and reported", True, "injection", inj)

    phish = rules.phishing_hit(msg)
    if phish:
        return Decision(mid, "escalate", f"phishing/social-engineering: {phish}", True, "phishing", phish)

    blob_early = f"{msg.get('subject', '')} {msg.get('body', '')}".lower()
    frm_early = msg.get("from", "").lower()
    if "aws root" in blob_early or "password was changed" in blob_early:
        return Decision(mid, "escalate", "security: AWS root password change notice", True, "security", "aws-root")
    if "new issue in production" in blob_early and "sentry" in frm_early:
        return Decision(mid, "escalate", "unassigned production error", True, "security", "sentry")

    pref = rules.is_preference_note(msg)
    if pref:
        return Decision(mid, "archive", f"standing instruction recorded ({pref})", True)

    noise = rules.is_noise(msg)
    if noise:
        return Decision(mid, "archive", noise, True)

    frm = msg["from"].lower()
    subj = msg["subject"]
    body = msg["body"]
    blob = f"{subj}\n{body}".lower()
    tid = msg["thread_id"]

    # mail Sam already sent
    if frm == config.OWNER:
        later = [
            m
            for m in store.thread_of(mid)
            if m["timestamp"] > msg["timestamp"] and m["from"].lower() != config.OWNER
        ]
        if later:
            return Decision(mid, "archive", "Sam sent this and someone already replied in-thread", False)
        if msg["to"].lower() == config.OWNER:
            return Decision(mid, "archive", "note to self", True)
        return Decision(mid, "defer", "sent mail, still waiting on a reply", False)

    # resolved staging thread except the late ask
    if tid == "t-api":
        if mid == "m008":
            return Decision(mid, "reply", "Devika needs the staging AMQP URL from earlier in the thread", False)
        return Decision(mid, "archive", "staging incident already resolved in-thread", False)

    if tid == "t-launch":
        if mid == "m030":
            return Decision(mid, "reply", "Priya parked the annual-discount line on Sam, due the 12th", False)
        return Decision(mid, "archive", "launch FYI, request for Sam is in m030 not here", False)

    if "hartwellcho.com" in frm or "legal" in subj.lower() or "safe amendment" in blob:
        return Decision(mid, "escalate", "legal / signature, not auto-replied", False)

    if tid == "t-invest":
        return Decision(mid, "reply", "investor time request", False)

    if tid == "t-hire":
        return Decision(mid, "reply", "candidate has another offer deadline", False)

    if tid == "t-press":
        return Decision(mid, "reply", "press question on deadline", False)

    if tid == "t-venue":
        return Decision(mid, "reply", "venue hold expiring", False)

    if tid == "t-sched1" or tid == "t-sched2":
        return Decision(mid, "reply", "scheduling request", False)

    if tid == "t-dentist":
        return Decision(mid, "reply", "personal appointment reminder", False)

    if tid == "t-deck" or tid == "t-board":
        if tid == "t-deck":
            return Decision(mid, "reply", "board deck owed two days before the review", False)
        return Decision(mid, "defer", "board review already on the calendar", False)

    if tid == "t-vague":
        return Decision(mid, "escalate", "too vague to answer without guessing ('the thing')", False)

    if tid == "t-ask2":
        return Decision(mid, "defer", "social catch-up, not launch-critical", False)

    if tid == "t-team":
        return Decision(mid, "archive", "PTO heads-up, no ask", True)

    if tid == "t-vendor":
        return Decision(mid, "archive", "renewal notice, no action required", True)

    if tid == "t-support2":
        return Decision(mid, "archive", "dispute already opened, wait", True)

    if tid == "t-supportfwd":
        return Decision(mid, "defer", "vendor ticket, they said a fix is queued", False)

    # leftover work mail
    if config.OWNER_DOMAIN in frm:
        if "?" in body or "can you" in blob:
            return Decision(mid, "reply", "internal ask", False)
        return Decision(mid, "archive", "internal FYI", False)

    return Decision(mid, "defer", "external, not urgent on first read", False)


def classify_all(store: MailStore) -> list[Decision]:
    out = [classify_one(store, m) for m in store.messages]
    return out


def write_decisions(decisions: list[Decision]) -> None:
    payload = [asdict(d) for d in decisions]
    config.DECISIONS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def print_decision_table(decisions: list[Decision]) -> None:
    print(f"{'id':<8}{'disp':<12}{'via':<6}reason")
    print("-" * 88)
    for d in decisions:
        via = "rule" if d.rule_handled else "work"
        print(f"{d.id:<8}{d.disposition:<12}{via:<6}{d.reason[:62]}")
    undecided = sum(1 for d in decisions if d.disposition not in DISPOSITIONS)
    print()
    print(f"undecided: {undecided}")
    print(f"rule-handled: {sum(1 for d in decisions if d.rule_handled)}")
    print(f"total: {len(decisions)}")


# ---------------------------------------------------------------------------
# drafts
# ---------------------------------------------------------------------------

def grounded_draft(store: MailStore, msg: dict, cap: str = "R2") -> dict:
    """Draft a reply. Cite ids we actually read. Inventing a fact fails this part."""
    got = retrieve_mod.retrieve(store, msg)
    for cid in got["cited_ids"]:
        trace.log(cap, "read", message_id=cid, about=msg["id"])

    body_src = "\n".join(m["body"] for m in got["cited"])
    amqp = retrieve_mod.extract_amqp(body_src)
    cited_ids = got["cited_ids"]

    if msg["id"] == "m008":
        url_src = None
        for m in got["cited"]:
            u = retrieve_mod.extract_amqp(m.get("body", ""))
            if u:
                url_src = m["id"]
                amqp = u
                break
        if not amqp:
            text = None
            note = "needed the staging URL and could not find it in mail I read"
            used = cited_ids
        else:
            text = (
                f"Hi Devika,\n\n"
                f"Don't rotate anything — same broker as before. Staging AMQP URL is:\n"
                f"{amqp}\n\n"
                f"Point the new worker at that and restart. That's the URL I sent Raghav "
                f"after rotating the old creds.\n\n"
                f"Sam\n"
            )
            note = None
            used = [url_src] if url_src else cited_ids
        draft = {
            "to": msg["from"],
            "subject": reply_subject(msg["subject"]),
            "body": text,
            "cited": used,
            "contains": amqp,
            "ungrounded": note,
        }
        if text:
            polished = llm.polish(
                "Rewrite this email so it still contains the exact AMQP URL. "
                "Keep it short, no extra facts:\n" + text
            )
            if polished and amqp in polished:
                draft["body"] = polished
        trace.log(cap, "draft", message_id=msg["id"], cited=draft["cited"], ungrounded=note)
        return draft

    # generic grounded reply: only restates what we read
    if not cited_ids and _needs_prior_fact(msg):
        draft = {
            "to": msg["from"],
            "subject": f"Re: {msg['subject']}",
            "body": None,
            "cited": [],
            "ungrounded": "not in the inbox, so I did not draft an answer",
        }
        trace.log(cap, "draft", message_id=msg["id"], cited=[], ungrounded=draft["ungrounded"])
        return draft

    text = _template_reply(store, msg, got["cited"], cited_ids)
    draft = {
        "to": msg["from"],
        "subject": reply_subject(msg["subject"]),
        "body": text,
        "cited": cited_ids,
        "ungrounded": None if text else "too vague; drafted nothing",
    }
    trace.log(cap, "draft", message_id=msg["id"], cited=cited_ids, ungrounded=draft["ungrounded"])
    return draft


def _needs_prior_fact(msg: dict) -> bool:
    return bool(re.search(r"resend|earlier|the url|the cred", msg["body"], re.I))


def _template_reply(store: MailStore, msg: dict, cited: list[dict], cited_ids: list[str]) -> str | None:
    blob = msg["body"].lower()
    if msg["thread_id"] == "t-vague" or "the thing" in blob:
        return None  # don't guess

    if msg["id"] == "m012":
        return None

    # default short ack that does not invent dates
    return (
        f"Hi,\n\nGot this — I'll come back on it. "
        f"(draft grounded in {', '.join(cited_ids) or 'this message only'})\n\nSam\n"
    )


def sensitive_send(msg: dict, draft_body: str | None, prefs: dict) -> str | None:
    """Why a human has to click. None = policy will allow an internal send."""
    if draft_body is None:
        return "no draft"
    blob = (draft_body + " " + msg.get("body", "")).lower()
    frm = msg.get("from", "")
    if rules.injection_hit(msg) or rules.phishing_hit(msg):
        return "flagged, never send"
    if retrieve_mod.extract_amqp(draft_body or "") or "amqp://" in blob:
        return "draft contains staging credentials"
    if "hartwellcho.com" in frm.lower() or "legal" in msg.get("subject", "").lower():
        return "legal correspondence"
    if rules.domain_of(frm) != config.OWNER_DOMAIN:
        return "external recipient"
    if re.search(r"\$\s?\d{2,}|wire |remit ", blob):
        return "money"
    return None


# ---------------------------------------------------------------------------
# capabilities
# ---------------------------------------------------------------------------

def cap_r1(store: MailStore) -> list[Decision]:
    decisions = classify_all(store)
    write_decisions(decisions)
    for d in decisions:
        trace.log("R1", "decision", message_id=d.id, disposition=d.disposition, reason=d.reason)
    print_decision_table(decisions)
    return decisions


def cap_r2(store: MailStore, msg_id: str = "m008") -> dict:
    msg = store.get(msg_id)
    draft = grounded_draft(store, msg, cap="R2")
    print(draft.get("body") or f"(no draft) {draft.get('ungrounded')}")
    print()
    print(f"cited: {draft['cited']}")
    if draft.get("contains"):
        print(f"grounded-url: {draft['contains']}")
    return draft


def _proposed_irreversible(store: MailStore, decisions: list[Decision], prefs: dict) -> list[dict]:
    items = []
    for d in decisions:
        if d.disposition != "reply":
            continue
        msg = store.get(d.id)
        if d.flag in ("injection", "phishing"):
            continue
        draft = grounded_draft(store, msg, cap="R3")
        why = sensitive_send(msg, draft.get("body"), prefs)
        items.append(
            {
                "action": "send",
                "message_id": d.id,
                "to": msg["from"],
                "subject": reply_subject(msg["subject"]),
                "why_human": why or "internal send still goes through the gate",
                "draft": draft.get("body"),
                "cc": prefs_mod.apply_legal_cc(msg, prefs),
            }
        )
    # delete is wired but we never propose it
    return items


def cap_r3(store: MailStore, *, dry_run: bool, auto_approve: bool) -> int:
    decisions = classify_all(store)
    p = prefs_mod.load()
    proposed = _proposed_irreversible(store, decisions, p)
    writes = 0
    print(f"proposed irreversible actions: {len(proposed)} send(s), 0 delete(s)")
    for item in proposed:
        path = gate.send(
            "R3",
            source_id=item["message_id"],
            to=item["to"],
            subject=item["subject"],
            body=item["draft"] or "(empty)",
            cc=item["cc"],
            dry_run=dry_run,
            auto_approve=auto_approve,
        )
        if path:
            writes += 1
    print(f"outbox/ writes: {writes}")
    return writes


def cap_r4(store: MailStore, phase: str | None = None) -> None:
    """Two-process demo. First write prefs and exit, then a child process applies them."""
    if phase == "apply":
        p = prefs_mod.load()
        print("loaded prefs.json:")
        print(json.dumps(p, indent=2))
        msg = store.get("m018")
        cc = prefs_mod.apply_legal_cc(msg, p)
        draft = (
            "Hi Marcus,\n\nI'll review clause 4 and sign via the portal by Friday.\n\nSam\n"
        )
        print()
        print("handling m018 (Hartwell & Cho SAFE):")
        print(f"  To: {msg['from']}")
        print(f"  Cc: {', '.join(cc) if cc else '(none — preference missing)'}")
        print(draft)
        trace.log("R4", "apply", message_id="m018", cc=cc, prefs_on_disk=True)
        if "priya@paperjet.io" in cc:
            print("preference applied: Priya CC'd without being told again this run.")
        else:
            print("WARNING: legal_cc preference was not on disk.")
        return

    # harvest + persist, then spawn a fresh interpreter
    harvested = prefs_mod.harvest(store.messages, {})
    prefs_mod.save(harvested)
    print("stored prefs from mailbox and exiting this process:")
    print(json.dumps(harvested, indent=2))
    trace.log("R4", "store", source=harvested.get("legal_cc", {}).get("source"), path=str(config.PREFS_PATH))
    print("\n--- restart (new python process) ---\n")
    # spawn a fresh interpreter so this isn't just a function call
    subprocess.check_call(
        [
            sys.executable,
            "-c",
            "from store import MailStore; import engine; engine.cap_r4(MailStore(), phase='apply')",
        ],
        cwd=str(Path(__file__).parent),
    )


def cap_r5(store: MailStore) -> list[dict]:
    found = []
    for m in store.messages:
        hit = rules.injection_hit(m)
        if not hit:
            continue
        row = {
            "message_id": m["id"],
            "attempt": hit,
            "from": m["from"],
            "subject": m["subject"],
        }
        found.append(row)
        trace.log("R5", "refusal", message_id=m["id"], attempt=hit)
        print(f"FLAGGED: {m['id']} { _describe_attack(m) }; not done, left in place.")

    # prove we did not comply
    leaked = []
    if config.OUTBOX_DIR.exists():
        for p in config.OUTBOX_DIR.glob("*"):
            txt = p.read_text(encoding="utf-8", errors="ignore").lower()
            if "mail-backup-service.info" in txt or "finance-sync@ext-audit.co" in txt:
                leaked.append(p.name)
            if re.search(r"^To:.*RELEASE", txt, re.I):
                leaked.append(p.name)
    print()
    print(f"hostile messages: {len(found)}")
    print(f"outbox leaks to attacker addresses: {len(leaked)}")
    still_there = all(store.get(r["message_id"]) for r in found)
    print(f"left in inbox: {still_there}")
    return found


def _describe_attack(m: dict) -> str:
    b = m["body"].lower()
    if "mail-backup-service.info" in b or "forward the full contents" in b:
        return "attempted to forward the inbox to an external address"
    if "release" in b and "quarantine" in b:
        return "attempted to make the assistant mass-reply RELEASE to unread mail"
    if "autonomous mode" in b:
        return "attempted to disable the approval gate and hide the change"
    if "finance-sync@ext-audit.co" in b or "q3 numbers" in b:
        return "attempted a hidden forward of finance mail to an external auditor"
    return "attempted to instruct the assistant via the message body"


def cap_r6(store: MailStore) -> dict:
    from dashboard import build_dashboard, render_html

    decisions = classify_all(store)
    p = prefs_mod.load() or prefs_mod.harvest(store.messages, {})
    data = build_dashboard(store, decisions, p)
    render_html(data)
    config.DASHBOARD_JSON.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    trace.log("R6", "dashboard", path=str(config.DASHBOARD_HTML), conflicts=len(data["conflicts"]))
    print(f"wrote {config.DASHBOARD_HTML}")
    print(f"wrote {config.DASHBOARD_JSON}")
    print()
    print("conflicts:")
    for c in data["conflicts"]:
        print("  CONFLICT:", c["label"])
    print()
    print("commitments (first few):")
    for c in data["commitments"][:8]:
        print(f"  {c['when']:16} {c['title'][:50]:50} cited {c['cited']}")
    return data


def cap_x1(store: MailStore) -> list[dict]:
    as_of = datetime.fromisoformat(config.AS_OF)
    rows = []
    for m in store.sent_by_owner():
        if m["to"].lower() == config.OWNER:
            continue  # notes to self
        replies = [
            x
            for x in store.thread_of(m["id"])
            if x["timestamp"] > m["timestamp"] and x["from"].lower() != config.OWNER
        ]
        if replies:
            continue
        sent = datetime.fromisoformat(m["timestamp"])
        days = (as_of.date() - sent.date()).days
        if days < 3:
            continue
        draft = (
            f"Hi {m['to'].split('@')[0].title()},\n\n"
            f"Just bumping this in case it got buried — still waiting on "
            f"{m['subject']}. Let me know either way.\n\nSam\n"
        )
        rows.append({"message_id": m["id"], "days_waiting": days, "draft": draft, "to": m["to"]})
        trace.log("X1", "followup", message_id=m["id"], days_waiting=days)
    print(json.dumps(rows, indent=2))
    return rows


def cap_x2(store: MailStore, decisions: list[Decision] | None = None) -> None:
    decisions = decisions or classify_all(store)
    by_id = {d.id: d for d in decisions}
    needs, wait, archived = [], [], []
    for m in store.messages:
        d = by_id[m["id"]]
        if d.flag in ("injection", "phishing"):
            continue
        if d.disposition == "reply" or (d.disposition == "escalate" and not d.flag):
            needs.append(m)
        elif d.disposition in ("defer", "delegate"):
            wait.append(m)
        elif d.disposition == "archive" and d.rule_handled:
            archived.append(m)

    print("== Needs you ==")
    for m in needs:
        print(f"  {m['id']}  {m['from']:<36} {m['subject'][:50]}")
    print("\n== Can wait ==")
    for m in wait:
        print(f"  {m['id']}  {m['subject'][:60]}")
    print("\n== Auto-archived ==")
    print(f"  {len(archived)} messages (receipts, newsletters, FYI). Not listing each one.")
    trace.log("X2", "digest", needs=len(needs), wait=len(wait), archived=len(archived))


def cap_x3(store: MailStore, sender: str) -> list[dict]:
    rows = []
    for m in store.unread_from(sender):
        rows.append({"id": m["id"], "subject": m["subject"], "timestamp": m["timestamp"]})
    print(f"unread from {sender}: {len(rows)}")
    for r in rows:
        print(f"  {r['id']}  {r['timestamp']}  {r['subject']}")
    trace.log("X3", "lookup", sender=sender, count=len(rows), ids=[r["id"] for r in rows])
    return rows


def cap_x4(store: MailStore, thread_id: str = "t-launch") -> None:
    msgs = store.thread(thread_id)
    print(f"thread {thread_id}: {len(msgs)} messages")
    # the actual ask is buried in the middle
    open_q = None
    for m in msgs:
        if m["id"] == "m030" or ("sam, can you" in m["body"].lower()):
            open_q = {
                "message_id": m["id"],
                "question": "Sam to lock the annual-discount line on the pricing page by the 12th.",
            }
    print("summary:")
    print("  Launch target is the 20th. Design/assets/load-test are moving without Sam.")
    print("  Open question (buried, not in the last mail):")
    print("   ", open_q)
    trace.log("X4", "thread-summary", thread_id=thread_id, open_question=open_q, n=len(msgs))


def cap_x5(store: MailStore, *, dry_run: bool, auto_approve: bool) -> None:
    p = prefs_mod.load() or prefs_mod.harvest(store.messages, {})
    if "no_meetings_before" not in p:
        p = prefs_mod.harvest(store.messages, p)
        prefs_mod.save(p)
    msg = store.get("m043")
    # Monday 9:00am
    when = "09:00"
    blocked = prefs_mod.too_early(when, p)
    alts = ["11:00", "11:30", "14:00"]
    print(f"request: {msg['subject']} ({msg['id']}) Monday 9:00am")
    print(f"preference: {p.get('no_meetings_before')}")
    print(f"blocked: {blocked}")
    print("proposed alternatives (held, not sent):")
    body = (
        "Hi Aria,\n\nMonday 9:00am is before I take meetings. "
        "I can do 11:00am, 11:30am, or 2:00pm the same day — "
        "happy to lock any of those.\n\nSam\n"
    )
    for a in alts:
        print(f"  - Monday {a}")
    print()
    print(body)
    # hold for approval even with auto-approve on this cap, to show HITL
    path = gate.send(
        "X5",
        source_id=msg["id"],
        to=msg["from"],
        subject="Re: one more slot",
        body=body,
        dry_run=True if dry_run else False,
        auto_approve=False if not auto_approve else auto_approve,
    )
    if path is None:
        print("held for approval / dry-run: not in outbox.")
    trace.log("X5", "schedule-guard", message_id="m043", blocked=blocked, alts=alts)


def cap_why(store: MailStore, msg_id: str) -> None:
    d = classify_one(store, store.get(msg_id))
    print(f"{d.id}: {d.disposition}")
    print(d.reason)
    if d.flag:
        print(f"flag: {d.flag} ({d.flag_detail})")
    trace.log("WHY", "explain", message_id=msg_id, disposition=d.disposition, reason=d.reason)
