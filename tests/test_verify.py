import asyncio

from forum.engine import Orchestrator
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.report import summarize
from forum.roster import loads
from forum.verify import NullVerifier, Verification

ROSTER = loads(
    """
[[agent]]
name="backend"
category="engineering"
domain="apis"
keywords=["api"]
model_tier="capable"
executor="echo"
"""
)


class _Exec:
    async def run(self, a):
        agent = a.agent
        if agent == "coordinator":
            return Result(a.task_id, agent, '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build", "depends_on": []}]}')
        if agent == "validator":
            return Result(a.task_id, agent, '{"ok": true, "score": 0.9, "reason": "ok"}')
        if agent == "synthesizer":
            return Result(a.task_id, agent, "the final answer")
        return Result(a.task_id, agent, "did it")


class _Verifier:
    """A scripted external verifier returning a fixed verdict."""

    def __init__(self, ok, source="checker"):
        self._ok = ok
        self._source = source

    def verify(self, request, answer):
        return Verification(ok=self._ok, detail="checked", source=self._source)


class _Abstain:
    def verify(self, request, answer):
        return None


def _led():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _run(led, verifier=None):
    orch = Orchestrator(
        ROSTER, led, _Exec(),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2),
        verifier=verifier,
    )
    asyncio.run(orch.submit("build the api"))


def test_null_verifier_is_the_default_and_witnesses_nothing():
    led = _led()
    _run(led)  # default verifier
    assert led.query(kind="verification") == []


def test_explicit_null_verifier_abstains():
    led = _led()
    _run(led, verifier=NullVerifier())
    assert led.query(kind="verification") == []


def test_abstaining_verifier_witnesses_nothing():
    led = _led()
    _run(led, verifier=_Abstain())
    assert led.query(kind="verification") == []


def test_verifier_verdict_is_witnessed_and_chained_to_the_answer():
    led = _led()
    _run(led, verifier=_Verifier(ok=True, source="index"))
    v = led.query(kind="verification")
    assert len(v) == 1
    body = led.get_payload(v[0].payload_hash)
    assert body == {"ok": True, "detail": "checked", "source": "index"}
    parent = led.get(v[0].causal_parent)  # chained to the synthesized answer
    assert parent.kind == "result" and "answer" in led.get_payload(parent.payload_hash)
    assert led.verify(deep=True) is True


def test_summary_counts_verifications_and_refutations():
    led = _led()
    _run(led, verifier=_Verifier(ok=False))
    s = summarize(led)
    assert s["verifications"] == 1
    assert s["verifications_refuted"] == 1


def test_verification_ok_none_is_witnessed_but_not_a_refutation():
    led = _led()
    _run(led, verifier=_Verifier(ok=None))
    s = summarize(led)
    assert s["verifications"] == 1
    assert s["verifications_refuted"] == 0  # None is "could not decide", not a refutation
