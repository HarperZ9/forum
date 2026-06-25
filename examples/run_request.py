"""Forum planning and answering a plain request, witnessed end to end.

A scripted executor stands in for a real model so this runs offline. In real
use, pass an ApiExecutor (or a model CLI via SubprocessExecutor) instead.

Run:  python examples/run_request.py        # no install, nothing to download
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

[[agent]]
name = "docs"
category = "support"
domain = "documentation"
keywords = ["docs"]
model_tier = "cheap"
executor = "scripted"
"""
)


class ScriptedExecutor:
    async def run(self, assignment):
        agent = assignment.agent
        if agent == "coordinator":
            out = (
                '{"tasks": ['
                '{"id": "T1", "agent": "backend", "instruction": "design the schema", "depends_on": []},'
                '{"id": "T2", "agent": "docs", "instruction": "document the schema", "depends_on": ["T1"]}'
                "]}"
            )
        elif agent == "validator":
            out = '{"ok": true, "score": 0.9, "reason": "looks right"}'
        elif agent == "synthesizer":
            out = "Shipped: a schema and its documentation."
        else:
            out = "handled: " + assignment.instruction
        return Result(assignment.task_id, assignment.agent, out)


def main() -> None:
    ticks = iter(float(t) for t in range(1, 100_000))
    ledger = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        ROSTER, ledger, ScriptedExecutor(),
        Policy(allowed_categories=frozenset({"engineering", "support"}), max_parallel=2),
    )

    answer = asyncio.run(orch.submit("build a schema and document it"))

    print("answer           :", answer)
    print("ledger entries   :", len(ledger.replay()))
    print("verdicts          :", len(ledger.query(kind="verdict")))
    print("verify(deep=True):", ledger.verify(deep=True))


if __name__ == "__main__":
    main()
