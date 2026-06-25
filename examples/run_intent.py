"""Forum: did the run answer the question? The witnessed intent check (v1.4).

Each task is validated against its own instruction, but a run can pass every task and
still drift from the original request. After synthesis, Forum witnesses an intent
check: a deterministic, reproducible coverage of the request's vocabulary by the final
answer. A low score flags a run for a closer look; it is a floor, not a verdict.

Here the same request gets two answers, one that addresses it and one that drifts. The
witnessed intent_check tells them apart, from the record. Scripted executors stand in
so this runs offline.

Run:  python examples/run_intent.py        # no install, nothing to download
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
domain = "apis"
keywords = ["api"]
model_tier = "capable"
executor = "scripted"
"""
)

REQUEST = "build the login api and the database schema"


class Scripted:
    """A scripted control loop whose synthesized answer is fixed per run."""

    def __init__(self, answer: str) -> None:
        self._answer = answer

    async def run(self, a):
        agent = a.agent
        if agent == "coordinator":
            return Result(a.task_id, agent, '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build it", "depends_on": []}]}')
        if agent == "validator":
            return Result(a.task_id, agent, '{"ok": true, "score": 0.9, "reason": "ok"}')
        if agent == "synthesizer":
            return Result(a.task_id, agent, self._answer)
        return Result(a.task_id, agent, "did the work")


def _run(answer: str) -> dict:
    ticks = iter(float(t) for t in range(1, 100_000))
    led = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        ROSTER, led, Scripted(answer),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2),
    )
    asyncio.run(orch.submit(REQUEST))
    return led.get_payload(led.query(kind="intent_check")[0].payload_hash)


def _show(label: str, answer: str, check: dict) -> None:
    print(f"{label}: {answer!r}")
    print("  coverage :", check["coverage"])
    print("  flagged  :", check["flagged"])
    print("  missing  :", check["missing"])
    print()


def main() -> None:
    print("request:", REQUEST)
    print()
    a = "build the login api and the database schema, with migrations"
    b = "done, see the attached notes"
    c = "implemented user authentication and the relational data model for the api"
    _show("answer A (on point, reuses the words)", a, _run(a))
    _show("answer B (drifted, says nothing)     ", b, _run(b))
    _show("answer C (correct but paraphrased)   ", c, _run(c))
    print("A and B behave as you would hope. C is the floor's known blind spot: a")
    print("correct answer that reuses few of the request's words still flags. That is")
    print("why this is a lexical floor, not a verdict, and why a grounded model")
    print("intent-judge is the next rung above it.")


if __name__ == "__main__":
    main()
