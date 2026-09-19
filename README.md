# inboxHero

**Student:** P Roopa, 1179353  
**Repository:** git history is in this project (see `git log`). I could not log into personal GitHub from this machine, so the public URL is not here yet. Do not use a work/org GitHub for this.

Assignment 6 — empty Sam's inbox without doing the dumb / dangerous bits.

```
python demo.py --cap R1
python demo.py --all
```

Copy `.env.example` to `.env` if you have a Gemini key. You don't need one. I
built the whole thing so the rule path + templates run offline. Gemini is only
there to polish a draft if a key is set.

## What it is

One Python pipeline, no CrewAI / ADK. Messages get loaded, the obvious ones
(receipts, newsletters, calendar nags) are archived by rules, and the rest go
classify → retrieve → draft → gate. A last pass writes the dashboard.

I reused the persistence idea from `memory.py` in assignment 5 (`prefs.py` is
the same trick: JSON on disk, process exits, next process reads it).

## Assumptions

- `inbox.json` is 100 messages, keys as in the spec. I didn't invent extra fields.
- "Now" is frozen to **2026-09-10** (`INBOXHERO_AS_OF`) because the mailbox only
  goes through 9 Sep. Otherwise every deadline looks overdue if you run this later.
- Owner is `sam@paperjet.io`. Sending = writing a file under `outbox/`.
- I never talk to a real mail server.

## Disposition vocab

| word | meaning |
|------|---------|
| reply | Sam owes a written answer |
| archive | done, noise, or already handled in-thread |
| defer | real, just not this morning |
| delegate | someone else should own it |
| escalate | a human has to look (legal, money, phish, vague, secrets) |

## Framework

None. This is a straight pipeline with one branch (rule vs work). A crew would
have been four YAML files to do a for-loop. See Final Report Q4.

## Retrieval

**Thread-walk**, keyword search as fallback. The inbox already has `thread_id`.
Embeddings on 100 messages felt like theatre. R2 walks `t-api` and pulls the
AMQP URL out of `m003` for the reply to `m008`.

If the fact isn't in mail I actually read, I don't draft. That's what happens
with `m012` ("the thing") — I escalate instead of guessing.

## Reversible vs irreversible

- **Irreversible:** `send`, `delete`. Send writes to `outbox/` and you can't
  unsend. Delete is irreversible because this mock store has no trash — once
  it's gone from `inbox.json` it's gone. I still don't delete anything.
- **Reversible:** `draft`, `label`, `archive`, `defer`. Drafts live in memory /
  the trace until a send is approved.

Both gates are implemented: `--dry-run` prints what it would do, and a live run
prompts `y/n` (or `--approve` if you want it non-interactive). Only `gate.send`
and `gate.delete` can cause those effects.

## Where I drew the line

I ask a human when the mail leaves `paperjet.io`, when it's legal, when money
moves, or when the draft contains creds (the staging AMQP URL). Internal
archives and defers just happen. Trade-off: I might archive a useful FYI
(Notion comments, a recovered Datadog ping) and Sam never sees it, but he also
isn't clicking "yes" forty times.

I will not auto-send a wire, a password reset, or anything that showed up as
an instruction *to the assistant*. `--approve` still cannot send those.

## Files

| file | what it does |
|------|----------------|
| `demo.py` | CLI (`--cap`, `--all`) |
| `engine.py` | classify / draft / the capability runners |
| `rules.py` | noise, phishing, injection — no model |
| `retrieve.py` | thread-walk + keyword |
| `gate.py` | the only send/delete |
| `prefs.py` | standing instructions on disk |
| `dashboard.py` | three panes → `dashboard.html` |
| `store.py` | load `inbox.json` |
| `trace.py` | `trace.jsonl` |
| `llm.py` | optional Gemini |
| `config.py` | env |

---

## Final Report

### 1. What did you refuse to automate?

`m012` from Priya — subject "the thing", body "that thing we talked about after
the standup". The system escalates and drafts nothing. Same for `m023` (wire
$3,200, "don't loop in finance", from `priya.nair@paperjet.co` which is not
our domain) and the SAFE on `m018`. I can draft a note that I'll review clause
4; I will not sign or pretend I did. The line is: if being wrong isn't
undoable, or I don't actually know what "the thing" is, a human does it.

### 2. Where does untrusted text enter your system?

Every body/subject is data. `rules.injection_hit` / `phishing_hit` run *before*
anything is drafted, and they never call a model. `gate.send` / `gate.delete`
are the only functions that can write outbox or drop mail, and they are not
callable from message text — there is no tool-calling loop the model can
invoke. An attacker has to (a) get past the scanner, then (b) get a human (or
`--approve`) to pass the gate. A prompt that says "ignore previous
instructions" inside `m024` never reaches a send. I also don't put hostile
bodies into Gemini even when a key is set; polish is only applied to *our*
draft of `m008`.

### 3. Who is accountable when it sends the wrong thing?

Sam is. The agent is a draft machine with a gate, not a principal. If a bad
mail goes out, `trace.jsonl` has the `read` ids, the `draft` (with `cited`),
and the `gate` decision (`dry-run` / `approved` / `denied` / `approved-auto`).
`outbox/<id>.txt` is the exact bytes. That's the paper trail I'd hand to
whoever is asking. `--approve` is me saying yes in bulk so a demo can run;
that's still a human action, just a lazy one.

### 4. Name your own machinery.

No framework, so the mapping is just functions:

- **Agents** — there aren't any. `engine.classify_one` and `engine.grounded_draft`
  are the two "roles".
- **Tasks** — one capability function each (`cap_r1` … `cap_x5`).
- **Crew** — `demo.py` running them in order.
- **Router** — `rules.is_noise` / `injection_hit` / `phishing_hit` splitting
  rule-path from work-path.

The thing a framework would have given me for free is a trace UI and retries.
I wrote `trace.py` myself (it's a jsonl dump) and a 429 retry in `llm.py`. A
CrewAI crew here would have hurt: I'd be wrapping a 15-line classifier in
agent cards, and the whole point of Part 2 is that most of this mail should
never touch a model.
