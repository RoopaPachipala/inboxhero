"""ROLL NUMBER: 1179353

A few checks that don't need a network. Run: python test_offline.py
"""

from engine import classify_all
from retrieve import extract_amqp, retrieve
from rules import injection_hit, phishing_hit
from store import MailStore


def main() -> None:
    store = MailStore()
    assert len(store.messages) == 100, len(store.messages)

    decisions = classify_all(store)
    assert len(decisions) == 100
    assert all(d.disposition in {"reply", "archive", "defer", "delegate", "escalate"} for d in decisions)

    # grounded URL lives in m003, asked for by m008
    draft_src = store.get("m003")["body"]
    url = extract_amqp(draft_src)
    assert url and url.startswith("amqp://")
    got = retrieve(store, store.get("m008"))
    assert "m003" in got["cited_ids"]

    hostile = {m["id"] for m in store.messages if injection_hit(m)}
    assert {"m017", "m024", "m039", "m047"} <= hostile, hostile

    phish = {m["id"] for m in store.messages if phishing_hit(m)}
    assert {"m021", "m023", "m045"} <= phish, phish

    print("offline checks ok")
    print("  messages", len(store.messages))
    print("  injections", sorted(hostile))
    print("  phishing", sorted(phish))
    print("  rule-handled", sum(1 for d in decisions if d.rule_handled))


if __name__ == "__main__":
    main()
