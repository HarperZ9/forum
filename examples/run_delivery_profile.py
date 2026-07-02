"""Forum: expert delivery profiles, witnessed prose contracts (v1.14).

Forum can witness whether a delivered answer meets a selected expert delivery
profile. The profile is deterministic: it flags generic model tells, filler,
indirect openings, and missing domain evidence without rewriting facts.

Run:  python examples/run_delivery_profile.py        # no install, nothing to download
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
            return Result(
                assignment.task_id,
                agent,
                "The module passes the focused test from the ledger. Ship the API.",
            )
        return Result(assignment.task_id, agent, "done")


def main() -> None:
    ticks = iter(float(t) for t in range(1, 1000))
    ledger = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        ROSTER,
        ledger,
        Executor(),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=1),
    )
    answer = asyncio.run(orch.submit("build the api", delivery_profile="engineer"))
    summary = summarize(ledger)
    print(answer)
    print("delivery profile checks:", summary["delivery_profile_checks"])
    print("delivery profile flagged:", summary["delivery_profile_flagged"])
    print("ledger verified:", summary["verified"])


if __name__ == "__main__":
    main()
