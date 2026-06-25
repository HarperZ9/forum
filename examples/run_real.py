"""Forum running a plan through real subprocess commands, witnessed end to end.

Each task here shells out to a real program (python one-liners stand in for
agents). Swap SubprocessExecutor's command for a model CLI (for example
["claude", "-p"]) or use ApiExecutor to drive an actual model.

Run:  python examples/run_real.py        # no install, nothing to download
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.dispatch import dispatch_plan
from forum.executor import SubprocessExecutor
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task


def main() -> None:
    ticks = iter(float(t) for t in range(1, 100_000))
    ledger = Ledger(InMemoryStorage(), clock=lambda: next(ticks))

    # A real executor: each task runs this program with the instruction as its argument.
    worker = SubprocessExecutor(
        [sys.executable, "-c", "import sys; print('handled:', sys.argv[1].upper())"]
    )

    plan = Plan(
        (
            Task("T1", "worker", "design schema", ()),
            Task("T2", "worker", "build endpoint", ("T1",)),
            Task("T3", "worker", "write docs", ("T2",)),
        )
    )

    results = asyncio.run(dispatch_plan(plan, ledger, worker, max_parallel=2))
    for tid in sorted(results):
        print(f"  {tid}: ok={results[tid].ok}  {results[tid].output}")

    print("ledger entries   :", len(ledger.replay()))
    print("verify(deep=True):", ledger.verify(deep=True))


if __name__ == "__main__":
    main()
