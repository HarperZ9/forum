"""Forum: witnessed model-tier escalation (v1.2).

A task whose output fails validation is retried up a ladder of stronger executors,
triggered by the witnessed verdict (auditable), not opaque model confidence. Every
attempt, escalation, and verdict is recorded, and each result names the model that
produced it. A scripted weak base and a strong model stand in so this runs offline.

Run:  python examples/run_escalation.py        # no install, nothing to download
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


class WeakBase:
    async def run(self, a):
        agent = a.agent
        if agent == "coordinator":
            return Result(a.task_id, agent, '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "design the api", "depends_on": []}]}')
        if agent == "validator":
            ok = "good" in a.instruction  # the validator judges the output embedded in its prompt
            return Result(a.task_id, agent, '{"ok": %s, "score": 0.5, "reason": "judged"}' % ("true" if ok else "false"))
        if agent == "synthesizer":
            return Result(a.task_id, agent, "Shipped (after escalation).")
        return Result(a.task_id, agent, "bad")  # the weak first attempt fails validation


class StrongModel:
    model_id = "frontier-model"

    async def run(self, a):
        return Result(a.task_id, a.agent, "good")  # the stronger model gets it right


def main() -> None:
    ticks = iter(float(t) for t in range(1, 100_000))
    led = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        ROSTER, led, WeakBase(),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2),
        escalation_executors=[StrongModel()],
    )
    answer = asyncio.run(orch.submit("build the api"))
    esc = led.query(kind="tier_escalation")
    verdicts = [led._s.get_payload(v.payload_hash)["ok"] for v in led.query(kind="verdict")]
    print("answer               :", answer)
    print("escalations          :", len(esc), "to", led._s.get_payload(esc[0].payload_hash)["to"] if esc else None)
    print("verdicts (fail->pass):", verdicts)
    print("verify(deep)         :", led.verify(deep=True))


if __name__ == "__main__":
    main()
