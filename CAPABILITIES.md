# CAPABILITIES.md

**Student:** P Roopa, 1179353
**Repository:** git history is in this checkout. Public GitHub will be a personal account, not a work org — this machine cannot open personal GitHub.

Run everything through one entry point:

```
python demo.py --cap R1        # one capability
python demo.py --all           # all of them, in the order below
```

A Gemini key is optional. Commands below work without one.

---

## The system, in one paragraph

A single Python pipeline, no framework. The 100-message `inbox.json` is loaded,
cheap mail (receipts, newsletters, calendar pings, internal filler) is archived
by rule, and the rest go classify → thread-walk → draft → gate. Preferences live
in `prefs.py` (JSON on disk, same idea as assignment 5). A last pass writes
`dashboard.html`. Sending means a file in `outbox/`. I never connect a real inbox.

## Design choices you were asked to state

- **Framework: none.** One branch (rule-path vs work-path). A crew/graph is
  overhead. See README Final Report Q4.
- **Retrieval: thread-walk.** `thread_id` is already an index. Keyword search is
  the fallback when the thread is empty. I did not use embeddings.
- **Reversible vs irreversible.** `send` and `delete` are irreversible and gated.
  `draft`, `label`, `archive`, `defer` are reversible. Delete is irreversible
  because the mock store has no trash — I still never delete.
- **Where the gate sits.** Only `gate.send` and `gate.delete` can do irreversible
  things, and both call `require_approval()` first. Hostile mail can change a
  *draft*; it cannot send without the gate. That's the Part 6 defence.
- **Escalation line.** Approve sends that leave paperjet.io, anything legal,
  anything with money, and anything with credentials (the AMQP URL in m003).
  Internal archives/defers are automatic. Trade-off: a useful FYI can get
  archived; Sam is not asked to rubber-stamp forty actions.
- **Messages processed:** 100. Format assumed as given (`id`, `thread_id`,
  `from`, `to`, `subject`, `timestamp`, `body`, `unread`). "Now" is 2026-09-10
  so the calendar matches the mailbox, not the day you run this.
- **Rule-handled count** is printed at the end of R1 (`rule-handled: 71`). Those
  never needed a model; I don't call Gemini for them even when a key exists.
- **Preference honoured:** `m015` — always CC `priya@paperjet.io` on Hartwell &
  Cho mail. After a restart this changes how `m018` is drafted.

## Capabilities

| id | name | tier | one-line claim |
|----|------|------|----------------|
| R1 | Zero the inbox | B | every message gets one disposition + reason, none left |
| R2 | Grounded reply | B | drafts cite the earlier message they used |
| R3 | Gate the irreversible | C | no send/delete without approval or --dry-run |
| R4 | Persistent preference | C | a stated preference survives a restart |
| R5 | Refuse embedded instructions | C | detects, refuses, flags, reports injections |
| R6 | Dashboard | C | three panes, commitments cited, conflicts surfaced |
| X1 | Follow-up tracking | B | unanswered sent mail, with a drafted chase |
| X2 | Morning digest | B | what needs me / what can wait / what was archived |
| X3 | Unread from sender | A | lists unread mail from one address |
| X4 | Buried ask in a long thread | B | launch thread summary + the actual open question |
| X5 | Guard the calendar | C | blocks a 9am against the 11am rule, holds three alts |

The exact command, observable outcome and evidence for each is in
`capabilities.json`. Keep the two in step.

## Final Report

Answers are in README.md (the spec asked for them there). Short version:

1. Refused to automate `m012` ("the thing") and any wire/legal signature.
2. Untrusted text is data; only `gate.py` can send, and it is not reachable from
   a message body.
3. Sam is accountable; `trace.jsonl` + `outbox/` are the audit trail.
4. classify / draft / demo.py / rules.py stand in for agents, tasks, crew, router.
