"""Forum: the engine running end-to-end (with a stub executor).

Routes a request, runs a dependency plan through the dispatcher, and verifies
the whole run from the ledger.

Run:  python examples/run.py        # zero dependencies, no install needed
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.engine import Orchestrator
from forum.executor import EchoExecutor
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task
from forum.policy import Policy
from forum.roster import loads

ROSTER = loads(
    """
[[agent]]
name = "backend"
category = "engineering"
domain = "apis and data"
keywords = ["api", "database", "schema", "auth", "endpoint"]
model_tier = "capable"
executor = "echo"

[[agent]]
name = "docs"
category = "support"
domain = "documentation"
keywords = ["docs", "readme", "guide"]
model_tier = "cheap"
executor = "echo"
"""
)


def main() -> None:
    ticks = iter(float(t) for t in range(1, 100_000))
    ledger = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        ROSTER, ledger, EchoExecutor(), Policy(allowed_categories=frozenset({"engineering", "support"}), max_parallel=2)
    )

    print("route 'design the auth endpoint' ->", orch.route("design the auth endpoint").decided)

    plan = Plan(
        (
            Task("T1", "backend", "design schema", ()),
            Task("T2", "backend", "build auth endpoint", ("T1",)),
            Task("T3", "docs", "write api docs", ("T2",)),
        )
    )
    results = asyncio.run(orch.submit_plan(plan))
    for tid in sorted(results):
        print(f"  {tid} [{results[tid].agent}] -> {results[tid].output}")

    print("ledger entries   :", len(ledger.replay()))
    print("verify(deep=True):", ledger.verify(deep=True))
    print("checkpoint       :", ledger.checkpoint()[:16] + "...")


if __name__ == "__main__":
    main()
