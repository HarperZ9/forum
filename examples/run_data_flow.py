"""Forum: the DAG flows data, typed edges (v1.6).

A dependency used to mean only "runs after." Now an edge has a type: a data edge
feeds the upstream's witnessed output into the downstream task so it can build on real
work, while an order edge only sequences. Both are witnessed, so the record shows not
just the order of work but what flowed between the steps.

Here T2 has a data edge on T1 (it sees T1's output) and T3 has an order edge on T1 (it
runs after, but sees nothing). The executor echoes the instruction it received, so the
injected upstream is visible. No model needed.

Run:  python examples/run_data_flow.py        # no install, nothing to download
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


class ShowExecutor:
    """Echoes the exact instruction it received, so injected upstream output is visible."""

    async def run(self, assignment):
        return Result(assignment.task_id, assignment.agent, assignment.instruction)


def main() -> None:
    ticks = iter(float(t) for t in range(1, 1000))
    led = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    plan = Plan(
        (
            Task("T1", "backend", "design the schema", ()),
            Task("T2", "backend", "build the api", ("T1",)),                      # data edge
            Task("T3", "ops", "send the deploy notice", ("T1",), frozenset({"T1"})),  # order edge
        )
    )
    results = asyncio.run(dispatch_plan(plan, led, ShowExecutor(), max_parallel=2))

    print("T2 (data edge on T1) saw:")
    print("   ", results["T2"].output.replace("\n", "\n    "))
    print()
    print("T3 (order edge on T1) saw:")
    print("   ", results["T3"].output)
    print()

    print("witnessed in the ledger:")
    for e in led.query(kind="task"):
        body = led.get_payload(e.payload_hash)
        print(f"  task {body['id']}: data_from={body['data_from']}")
    edges = led.get_payload(led.query(kind="plan")[0].payload_hash)["edges"]
    print("  plan edges:", edges)
    print("  verify(deep):", led.verify(deep=True))


if __name__ == "__main__":
    main()
