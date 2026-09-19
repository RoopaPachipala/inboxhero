"""ROLL NUMBER: 1179353

Single entry point for the marking script.

    python demo.py --cap R1
    python demo.py --all
"""

from __future__ import annotations

import argparse
import sys

import engine
import trace
from store import MailStore


ORDER = ["R1", "R2", "R3", "R4", "R5", "R6", "X1", "X2", "X3", "X4", "X5"]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="inboxHero")
    p.add_argument("--cap", help="R1..R6 or X1..X5")
    p.add_argument("--all", action="store_true", help="run every capability, in order")
    p.add_argument("--msg", default="m008", help="message id (R2)")
    p.add_argument("--from", dest="sender", default="priya@paperjet.io")
    p.add_argument("--thread", default="t-launch")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--approve", action="store_true", help="auto-approve gated sends this run")
    p.add_argument("--r4-phase", choices=["apply"], default=None)
    p.add_argument("--why", metavar="MSG", help="explain one decision")
    p.add_argument("--reset-trace", action="store_true")
    args = p.parse_args(argv)

    if args.reset_trace or args.all:
        trace.reset()

    store = MailStore()

    if args.why:
        engine.cap_why(store, args.why)
        return 0

    if args.all:
        caps = ORDER
    elif args.cap:
        caps = [args.cap.upper()]
    else:
        p.print_help()
        return 2

    for cap in caps:
        print(f"\n######## {cap} ########\n")
        _run(store, cap, args)
    return 0


def _run(store: MailStore, cap: str, args) -> None:
    if cap == "R1":
        engine.cap_r1(store)
    elif cap == "R2":
        engine.cap_r2(store, args.msg)
    elif cap == "R3":
        # Manifest command is a dry-run. --approve without --dry-run actually writes.
        use_dry = not (args.approve and not args.dry_run)
        if args.dry_run:
            use_dry = True
        engine.cap_r3(store, dry_run=use_dry, auto_approve=args.approve and not use_dry)
    elif cap == "R4":
        engine.cap_r4(store, phase=args.r4_phase)
    elif cap == "R5":
        engine.cap_r5(store)
    elif cap == "R6":
        engine.cap_r6(store)
    elif cap == "X1":
        engine.cap_x1(store)
    elif cap == "X2":
        engine.cap_x2(store)
    elif cap == "X3":
        engine.cap_x3(store, args.sender)
    elif cap == "X4":
        engine.cap_x4(store, args.thread)
    elif cap == "X5":
        engine.cap_x5(store, dry_run=True, auto_approve=False)
    else:
        sys.exit(f"unknown cap {cap}")


if __name__ == "__main__":
    raise SystemExit(main())
