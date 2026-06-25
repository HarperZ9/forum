"""Forum: a durable ledger that survives a restart (v0.5).

Writes a witnessed run to a file-backed ledger, drops it, then reopens the
same directory and shows the record is intact and still verifiable. The point
is durability: the ledger outlives the run.

Run:  python examples/run_durable.py        # zero dependencies, no install needed
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

# Make `forum` importable straight from a checkout (src layout), no install needed.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.ledger import Ledger
from forum.storage import FileStorage


def rule(title: str) -> None:
    print("\n" + title)
    print("-" * len(title))


def _clock():
    ticks = iter(float(t) for t in range(1, 100_000))
    return lambda: next(ticks)


def main() -> None:
    workdir = tempfile.mkdtemp(prefix="forum-ledger-")

    rule("1. Write a witnessed run to a file-backed ledger")
    led = Ledger(FileStorage(workdir), clock=_clock())
    req = led.append(actor="client", kind="request", payload={"text": "reconcile the books"})
    plan = led.append(actor="coordinator", kind="plan", payload={"tasks": ["T1"]}, causal_parent=req.seq)
    led.append(actor="auditor", kind="result", payload={"id": "T1", "output": "balanced"}, causal_parent=plan.seq)
    print(f"  wrote {len(led.replay())} entries to {workdir}")
    print(f"  checkpoint: {led.checkpoint()[:16]}...")

    rule("2. Drop the ledger and reopen the same directory (a 'restart')")
    reopened = Ledger(FileStorage(workdir))
    print(f"  recovered {len(reopened.replay())} entries")
    print(f"  verify(deep=True): {reopened.verify(deep=True)}")
    print(f"  checkpoint: {reopened.checkpoint()[:16]}...  (same root, the record held)")
    chain = reopened.causal_chain(2)
    print(f"  causal chain of last: {' -> '.join(e.kind for e in chain)}")


if __name__ == "__main__":
    main()
