"""Forum: efficiency, bounded prompts and a weighed record (v1.10).

Efficiency is measurable, so it can be verified like everything else. Two things here:
a data edge caps how much upstream output it injects into a downstream prompt (the full
output stays in the ledger, only the prompt shrinks), and the run summary weighs the
witnessed record so a leaner run is provable.

Run:  python examples/run_efficiency.py        # no install, nothing to download
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.dispatch import dispatch_plan
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task
from forum.report import summarize


class BigUpstream:
    """T1 emits a large output; T2 echoes the (capped) prompt it received."""

    async def run(self, a):
        if a.task_id == "T1":
            return Result("T1", a.agent, "x" * 20000)
        return Result(a.task_id, a.agent, a.instruction)


def main() -> None:
    ticks = iter(float(t) for t in range(1, 1000))
    led = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    plan = Plan((Task("T1", "backend", "produce a big artifact", ()), Task("T2", "backend", "use it", ("T1",))))
    results = asyncio.run(dispatch_plan(plan, led, BigUpstream(), max_parallel=2))

    full = next(
        led.get_payload(e.payload_hash)["output"]
        for e in led.query(kind="result")
        if led.get_payload(e.payload_hash).get("id") == "T1"
    )
    print("T1 full output length        :", len(full), "chars")
    print("T2 prompt length (capped)    :", len(results["T2"].output), "chars  <- bounded, not 20000+")
    print("full T1 output still witnessed:", len(full) == 20000)
    print("record weight (payload_bytes):", summarize(led)["payload_bytes"], "bytes")
    print("verify(deep)                 :", led.verify(deep=True))


if __name__ == "__main__":
    main()
