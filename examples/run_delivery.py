"""Forum: the delivery ladder, verified tightening (v1.11).

Model output tends to be word-dense, and the reader wants the shortest path to the
answer. forum.delivery.assess measures that objectively (sentence length, filler), the
way forum.intent measures coverage. When the floor flags a verbose answer and a Reviser
is configured, Forum pulls a tighter version and accepts it only if it is strictly
shorter AND still covers the request's terms (a lexical guard: it drops no request term,
but does not prove meaning is preserved). Scripted executors stand in so this runs offline.

Run:  python examples/run_delivery.py        # no install, nothing to download
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

REQUEST = "build the login api and the schema"
VERBOSE = "Honestly it is really very basically just actually quite simply the login api and the schema."


class Scripted:
    def __init__(self, answer: str) -> None:
        self._answer = answer

    async def run(self, a):
        agent = a.agent
        if agent == "coordinator":
            return Result(a.task_id, agent, '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build", "depends_on": []}]}')
        if agent == "validator":
            return Result(a.task_id, agent, '{"ok": true, "score": 0.9, "reason": "ok"}')
        if agent == "synthesizer":
            return Result(a.task_id, agent, self._answer)
        return Result(a.task_id, agent, "did it")


class Reviser:
    """A scripted reviser returning a fixed tightening (a model would do this for real)."""

    def __init__(self, revised: str) -> None:
        self._revised = revised

    def revise(self, request: str, answer: str) -> str:
        return self._revised


def _run(reviser) -> tuple[str, dict]:
    ticks = iter(float(t) for t in range(1, 1000))
    led = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        ROSTER, led, Scripted(VERBOSE),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2),
        reviser=reviser,
    )
    answer = asyncio.run(orch.submit(REQUEST))
    rev = led.get_payload(led.query(kind="revision")[0].payload_hash)
    return answer, rev


def main() -> None:
    print("request :", REQUEST)
    print("verbose answer (flagged by the floor):")
    print("   ", VERBOSE)
    print()

    answer, rev = _run(Reviser("the login api and the schema"))  # tighter and still covered
    print("reviser tightens, still covers the request:")
    print(f"  accepted: {rev['accepted']} | words {rev['words_before']} -> {rev['words_after']} | coverage {rev['coverage_before']} -> {rev['coverage_after']}")
    print("  delivered:", answer)
    print()

    answer, rev = _run(Reviser("done"))  # tighter but drops the request's terms
    print("reviser tightens but drops coverage:")
    print(f"  accepted: {rev['accepted']} | coverage {rev['coverage_before']} -> {rev['coverage_after']}")
    print("  delivered (original kept):", answer)


if __name__ == "__main__":
    main()
