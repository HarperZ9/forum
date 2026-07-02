"""Forum: context pressure, witnessed token admission (v1.13).

Context from a brain is useful only if its cost and risk are explicit. This example
applies approximate-token budgets to request context and per-task context. Forum
admits only the bounded text, witnesses every retained/trimmed/omitted decision, and
summarizes how many context tokens were saved.

Run:  python examples/run_context_pressure.py        # no install, nothing to download
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.context_budget import ContextBudget
from forum.engine import Orchestrator
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.report import summarize
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


class Brain:
    """A stand-in ContextProvider with more context than the run should admit."""

    def context(self, request: str) -> str:
        return "important-context " * 80


class Executor:
    async def run(self, assignment):
        agent = assignment.agent
        if agent == "coordinator":
            return Result(
                assignment.task_id,
                agent,
                '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build the api", "depends_on": []}]}',
            )
        if agent == "validator":
            return Result(assignment.task_id, agent, '{"ok": true, "score": 1.0, "reason": "ok"}')
        if agent == "synthesizer":
            return Result(assignment.task_id, agent, "Built the api.")
        return Result(assignment.task_id, agent, assignment.instruction)


def main() -> None:
    ticks = iter(float(t) for t in range(1, 1000))
    ledger = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        ROSTER,
        ledger,
        Executor(),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=1),
        context_provider=Brain(),
    )
    answer = asyncio.run(
        orch.submit(
            "build the api",
            context_budget=ContextBudget(
                max_total_tokens=40,
                max_request_tokens=20,
                max_task_tokens=20,
            ),
        )
    )
    summary = summarize(ledger)
    print(answer)
    print("context budget checks:", summary["context_budget_checks"])
    print("context tokens admitted:", summary["context_tokens_admitted"])
    print("context tokens saved:", summary["context_tokens_saved"])
    print("ledger verified:", summary["verified"])


if __name__ == "__main__":
    main()
