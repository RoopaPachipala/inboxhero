"""ROLL NUMBER: 1179353

Mail store. JSON in, threads and keyword search out. No model here.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

import config


class MailStore:
    def __init__(self, path: Path | None = None):
        self.path = path or config.INBOX_PATH
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        # keep original order but also index
        self.messages = list(raw)
        self.by_id = {m["id"]: m for m in self.messages}
        threads: dict[str, list] = defaultdict(list)
        for m in self.messages:
            threads[m["thread_id"]].append(m)
        for tid in threads:
            threads[tid].sort(key=lambda x: x["timestamp"])
        self.threads = dict(threads)

    def get(self, msg_id: str) -> dict:
        if msg_id not in self.by_id:
            raise KeyError(f"no message {msg_id}")
        return self.by_id[msg_id]

    def thread(self, thread_id: str) -> list[dict]:
        return list(self.threads.get(thread_id, []))

    def thread_of(self, msg_id: str) -> list[dict]:
        return self.thread(self.get(msg_id)["thread_id"])

    def earlier_in_thread(self, msg_id: str) -> list[dict]:
        msg = self.get(msg_id)
        out = []
        for m in self.thread_of(msg_id):
            if m["id"] == msg_id:
                break
            out.append(m)
        return out

    def keyword_search(self, query: str, exclude: str | None = None, k: int = 5) -> list[dict]:
        """Very small keyword search. Good enough for 100 messages."""
        tokens = [t for t in re.findall(r"[a-z0-9]{3,}", query.lower()) if t not in STOP]
        scored = []
        for m in self.messages:
            if m["id"] == exclude:
                continue
            blob = f"{m['subject']} {m['body']} {m['from']}".lower()
            score = sum(blob.count(t) for t in tokens)
            # boost if several tokens hit
            hits = sum(1 for t in tokens if t in blob)
            if hits:
                scored.append((score + hits * 2, m))
        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:k]]

    def sent_by_owner(self) -> list[dict]:
        return [m for m in self.messages if m["from"].lower() == config.OWNER]

    def unread_from(self, sender: str) -> list[dict]:
        sender = sender.lower()
        return [
            m
            for m in self.messages
            if m["from"].lower() == sender and m.get("unread")
        ]


STOP = {
    "the", "and", "for", "you", "your", "this", "that", "with", "from",
    "have", "are", "was", "were", "can", "just", "need", "please", "will",
}
