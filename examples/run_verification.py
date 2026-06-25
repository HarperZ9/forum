"""Forum: the verification seam (v1.7).

Forum plans on context from an external brain (the ContextProvider seam). Its peer on
the other end of the run is the VerifierProvider: after Forum produces an answer, an
external verifier checks it, and the verdict is witnessed. The default abstains, so
Forum stands alone; plug one in and the run gains an outside opinion on its record.

Here a trivial verifier requires the answer to mention a term. One run passes, one is
refuted, and both verdicts are witnessed. A real verifier could be a peer flagship, a
proof-checker, or a test runner. No model needed.

Run:  python examples/run_verification.py        # no install, nothing to download
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
from forum.verify import Verification

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


class Scripted:
    """A scripted control loop whose synthesized answer is fixed per run."""

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


class MentionsVerifier:
    """A trivial external verifier: the answer must mention a required term."""

    def __init__(self, required: str) -> None:
        self._required = required

    def verify(self, request: str, answer: str) -> Verification:
        ok = self._required.lower() in answer.lower()
        verb = "mentions" if ok else "omits"
        return Verification(ok=ok, detail=f"answer {verb} {self._required!r}", source="mentions-check")


def _run(answer: str) -> dict:
    ticks = iter(float(t) for t in range(1, 1000))
    led = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        ROSTER, led, Scripted(answer),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2),
        verifier=MentionsVerifier("login"),
    )
    asyncio.run(orch.submit("build the login api"))
    return led.get_payload(led.query(kind="verification")[0].payload_hash)


def main() -> None:
    print("verifier requires the answer to mention 'login'")
    print()
    for label, answer in [
        ("answer mentions it", "the login api is built and shipped"),
        ("answer omits it    ", "the endpoint is built and shipped"),
    ]:
        v = _run(answer)
        print(f"{label}: {answer!r}")
        print(f"  witnessed verification: ok={v['ok']} | {v['detail']} | source={v['source']}")
        print()


if __name__ == "__main__":
    main()
