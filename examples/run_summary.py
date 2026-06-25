"""Forum: reading the record, summary and ledger A/B (v1.3).

A witnessed run is only worth what you can learn from it. `summarize(ledger)` folds
a run into counts read purely from the ledger, and `compare(a, b)` reports the delta
between two runs, so an improvement is measured from the record rather than claimed.

Here run A uses a weak base model whose task output fails validation; run B swaps in a
stronger base model that passes. The summary of each is read straight from its ledger,
and the A/B delta shows the failure turning into a pass, the kind of result you would
otherwise have to take on faith. Scripted executors stand in so this runs offline.

Run:  python examples/run_summary.py        # no install, nothing to download
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.engine import Orchestrator
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.report import compare, summarize
from forum.roster import loads

ROSTER = loads(
    """
[[agent]]
name = "backend"
category = "engineering"
domain = "apis"
keywords = ["api"]
model_tier = "capable"
executor = "scripted"
"""
)


class ScriptedBase:
    """A scripted base model. `good` controls whether its task output passes validation."""

    def __init__(self, *, good: bool, model_id: str) -> None:
        self._good = good
        self.model_id = model_id

    async def run(self, a):
        agent = a.agent
        if agent == "coordinator":
            return Result(a.task_id, agent, '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "design the api", "depends_on": []}]}')
        if agent == "validator":
            ok = "good" in a.instruction  # the validator judges the output embedded in its prompt
            return Result(a.task_id, agent, '{"ok": %s, "score": 0.7, "reason": "judged"}' % ("true" if ok else "false"))
        if agent == "synthesizer":
            return Result(a.task_id, agent, "Shipped.")
        return Result(a.task_id, agent, "good" if self._good else "bad")


def _run(model: ScriptedBase) -> Ledger:
    ticks = iter(float(t) for t in range(1, 100_000))
    led = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        ROSTER, led, model,
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2),
    )
    asyncio.run(orch.submit("build the api"))
    return led


def main() -> None:
    a = summarize(_run(ScriptedBase(good=False, model_id="weak-1")))   # task fails validation
    b = summarize(_run(ScriptedBase(good=True, model_id="strong-1")))  # same request, stronger model

    print("run A summary (read straight from its ledger):")
    for key in ("requests", "tasks", "task_results", "verdicts_pass", "verdicts_fail", "answers"):
        print(f"  {key:<14}: {a[key]}")
    print(f"  {'model_calls':<14}: {a['model_calls']}")
    print(f"  {'verified':<14}: {a['verified']}")

    delta = compare(a, b)  # b - a, measured from the two records
    print("\nA/B delta (B - A), the change measured from the record:")
    print("  verdicts_fail :", "%+d" % delta["verdicts_fail"], "(fewer failures is the win)")
    print("  verdicts_pass :", "%+d" % delta["verdicts_pass"])
    print("  model_calls   :", a["model_calls"], "->", b["model_calls"])


if __name__ == "__main__":
    main()
