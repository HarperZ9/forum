"""Forum: the witnessed run contract - external context and a bounded run (v1.1).

Shows submit() consuming organized context from a ContextProvider (the seam to a
"brain" like the index flagship) and running under a RunBudget, with both the
context and the budget stop witnessed in the ledger. A scripted executor stands
in for a real model so this runs offline.

Run:  python examples/run_contract.py        # no install, nothing to download
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.budget import RunBudget
from forum.engine import Orchestrator
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.roster import loads

ROSTER = loads(
    """
[[agent]]
name = "backend"
category = "engineering"
domain = "apis and data"
keywords = ["api", "database"]
model_tier = "capable"
executor = "scripted"
"""
)


class ScriptedExecutor:
    async def run(self, assignment):
        agent = assignment.agent
        if agent == "coordinator":
            out = '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "design the schema", "depends_on": []}]}'
        elif agent == "validator":
            out = '{"ok": true, "score": 0.9, "reason": "ok"}'
        elif agent == "synthesizer":
            out = "Shipped: a schema informed by the provided context."
        else:
            out = "handled: " + assignment.instruction
        return Result(assignment.task_id, assignment.agent, out)


class DemoContext:
    def context(self, request: str) -> str:
        return "ACME standard: all services use Postgres; the api lane owns auth."


def rule(title: str) -> None:
    print("\n" + title)
    print("-" * len(title))


def _orch(provider=None):
    ticks = iter(float(t) for t in range(1, 100_000))
    ledger = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        ROSTER, ledger, ScriptedExecutor(),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2),
        context_provider=provider,
    )
    return ledger, orch


def main() -> None:
    rule("1. submit() with organized context from a provider (witnessed)")
    led, orch = _orch(provider=DemoContext())
    answer = asyncio.run(orch.submit("build the api"))
    print("answer         :", answer)
    print("context witnessed:", len(led.query(kind="context")) == 1)
    print("verify(deep)   :", led.verify(deep=True))

    rule("2. submit() under a RunBudget (stops gracefully, witnessed)")
    led2, orch2 = _orch()
    answer2 = asyncio.run(orch2.submit("build the api", budget=RunBudget(max_model_calls=1)))
    print("answer         :", answer2)
    print("budget witnessed:", len(led2.query(kind="budget")) == 1)
    print("verify(deep)   :", led2.verify(deep=True))


if __name__ == "__main__":
    main()
