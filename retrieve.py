"""ROLL NUMBER: 1179353

Retrieval: walk the thread first, keyword search if that is not enough.
"""

from __future__ import annotations

import re

from store import MailStore

SECRETISH = re.compile(r"(amqp://\S+|password|secret|token|creds?)", re.I)


def retrieve(store: MailStore, msg: dict, k: int = 4) -> dict:
    """Return {method, cited: [msgs], note}."""
    cited = []
    method = "thread-walk"

    for m in store.earlier_in_thread(msg["id"]):
        cited.append(m)

    # if the current mail is asking for something that looks like a fact
    # (URL, date, name) and the thread didn't have it, fall back to keywords
    q = f"{msg['subject']} {msg['body']}"
    need_more = False
    if re.search(r"\b(url|creds?|credentials?|password|amqp|link|when|where)\b", q, re.I):
        if not any(SECRETISH.search(m.get("body", "")) or "http" in m.get("body", "").lower() for m in cited):
            # thread might still have it without those words; check anyway
            if not cited:
                need_more = True
        # Devika asked to resend the URL Raghav got — that's in-thread
        if "resend" in q.lower() or "earlier" in q.lower():
            need_more = False

    extra = []
    if need_more or not cited:
        extra = store.keyword_search(q, exclude=msg["id"], k=k)
        if extra:
            method = "thread-walk+keyword" if cited else "keyword"
            for m in extra:
                if m["id"] not in {c["id"] for c in cited}:
                    cited.append(m)

    trace_read = [m["id"] for m in cited]
    return {"method": method, "cited": cited, "cited_ids": trace_read}


def extract_amqp(text: str) -> str | None:
    m = re.search(r"amqp://\S+", text)
    return m.group(0).rstrip(" .") if m else None
