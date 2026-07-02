"""Forum: context capsules, compact run memory (v1.15).

Context Capsules turn a witnessed ledger into a small local brief. A later run can
use that brief through the existing ContextProvider seam, so useful run state carries
forward without replaying the whole ledger into the model.

Run:  python examples/run_context_capsule.py        # no install, nothing to download
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.context_capsule import LedgerCapsuleProvider, build_context_capsule
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


class Executor:
    async def run(self, assignment):
        text = assignment.instruction
        agent = assignment.agent
        if agent == "coordinator":
            return Result(
                assignment.task_id,
                agent,
                '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build the api", "depends_on": []}]}',
            )
        if agent == "validator":
            return Result(assignment.task_id, agent, '{"ok": true, "score": 1.0, "reason": "ok"}')
        if agent == "synthesizer" and "extend" in text.lower():
            return Result(assignment.task_id, agent, "Extended the api from the capsule.")
        if agent == "synthesizer":
            return Result(assignment.task_id, agent, "Built the api.")
        return Result(assignment.task_id, agent, "handled")


def _orchestrator(ledger, context_provider=None):
    return Orchestrator(
        ROSTER,
        ledger,
        Executor(),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=1),
        context_provider=context_provider,
    )


def main() -> None:
    ticks = iter(float(t) for t in range(1, 1000))
    ledger = Ledger(InMemoryStorage(), clock=lambda: next(ticks))

    first = _orchestrator(ledger)
    asyncio.run(first.submit("build the api"))

    capsule = build_context_capsule(ledger)
    print("capsule schema:", capsule["schema"])
    print("latest answer:", capsule["latest_answer"])
    print("context text chars:", capsule["context_text_chars"])

    second = _orchestrator(ledger, context_provider=LedgerCapsuleProvider(ledger))
    asyncio.run(second.submit("extend the api"))

    context_payloads = [
        ledger.get_payload(entry.payload_hash)
        for entry in ledger.query(kind="context")
    ]
    witnessed = any("Forum context capsule" in payload.get("context", "") for payload in context_payloads)
    print("capsule context witnessed:", witnessed)


if __name__ == "__main__":
    main()
