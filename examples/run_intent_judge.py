"""Forum: the intent-judge, the grounded rung above the lexical floor (v1.5).

The lexical intent floor (v1.4) flags when an answer reuses few of the request's
words. Its blind spot: a correct but paraphrased answer flags too. The intent-judge
is the rung above it: when the floor flags, a model decides whether the answer truly
drifted or merely paraphrased. Cheap-first, the model runs only on a flag.

Here a paraphrased-but-correct answer and a genuinely drifted answer both flag the
floor; the judge clears the first and confirms the second. The judge is scripted so
this runs offline; in real use it is any model behind the executor seam.

Run:  python examples/run_intent_judge.py        # no install, nothing to download
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.control import IntentJudge
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
    """A scripted control loop. The synthesized answer and the judge's verdict are fixed."""

    def __init__(self, answer: str, judge_ok: bool) -> None:
        self._answer = answer
        self._judge_ok = judge_ok

    async def run(self, a):
        agent = a.agent
        if agent == "coordinator":
            return Result(a.task_id, agent, '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build it", "depends_on": []}]}')
        if agent == "validator":
            return Result(a.task_id, agent, '{"ok": true, "score": 0.9, "reason": "ok"}')
        if agent == "intent-judge":
            return Result(a.task_id, agent, '{"ok": %s, "score": 0.8, "reason": "scripted judgment"}' % ("true" if self._judge_ok else "false"))
        if agent == "synthesizer":
            return Result(a.task_id, agent, self._answer)
        return Result(a.task_id, agent, "did the work")


def _run(answer: str, judge_ok: bool):
    ticks = iter(float(t) for t in range(1, 100_000))
    led = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        ROSTER, led, Scripted(answer, judge_ok),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2),
        intent_judge=IntentJudge(),
    )
    asyncio.run(orch.submit(REQUEST))
    check = led.get_payload(led.query(kind="intent_check")[0].payload_hash)
    judgments = led.query(kind="intent_judgment")
    judgment = led.get_payload(judgments[0].payload_hash) if judgments else None
    return check, judgment


def _show(label: str, answer: str, check: dict, judgment: dict | None) -> None:
    print(f"{label}: {answer!r}")
    print(f"  floor: coverage {check['coverage']}, flagged {check['flagged']}")
    if judgment is None:
        print("  judge: not run (the floor did not flag)")
    else:
        verdict = "addresses the request" if judgment["ok"] else "judged real drift"
        print(f"  judge: ok={judgment['ok']} ({verdict})")
    print()


def main() -> None:
    print("request:", REQUEST)
    print()
    a = "implemented user authentication and the relational data model for the api"
    b = "done, see the attached notes"
    _show("paraphrased but correct", a, *_run(a, judge_ok=True))
    _show("genuinely drifted      ", b, *_run(b, judge_ok=False))
    print("Both answers flag the cheap lexical floor. The model judge is what separates")
    print("the correct paraphrase from the real drift, and its verdict is witnessed.")


if __name__ == "__main__":
    main()
