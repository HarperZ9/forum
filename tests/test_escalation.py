import asyncio

from forum.budget import RunBudget
from forum.engine import Orchestrator
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.roster import loads

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


class _Base:
    """Plans one backend task whose output is weak ("bad"); the validator fails
    "bad" and passes "good" (it reads the output embedded in its prompt)."""

    async def run(self, a):
        agent = a.agent
        if agent == "coordinator":
            return Result(a.task_id, agent, '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build", "depends_on": []}]}')
        if agent == "validator":
            ok = "good" in a.instruction
            return Result(a.task_id, agent, '{"ok": %s, "score": 0.5, "reason": "x"}' % ("true" if ok else "false"))
        if agent == "synthesizer":
            return Result(a.task_id, agent, "final")
        return Result(a.task_id, agent, "bad")


class _Strong:
    model_id = "strong-model"

    async def run(self, a):
        return Result(a.task_id, a.agent, "good")


class _Fixed:
    """An escalation rung that always returns a fixed output, with a given model id."""

    def __init__(self, output, model_id):
        self._output = output
        self.model_id = model_id

    async def run(self, a):
        return Result(a.task_id, a.agent, self._output)


def _led():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _orch(led, escalation=None):
    return Orchestrator(
        ROSTER, led, _Base(), Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2),
        escalation_executors=escalation,
    )


def _payloads(led, kind):
    return [led._s.get_payload(e.payload_hash) for e in led.query(kind=kind)]


def test_failed_task_escalates_to_a_stronger_executor():
    led = _led()
    asyncio.run(_orch(led, escalation=[_Strong()]).submit("build the api"))
    esc = led.query(kind="tier_escalation")
    assert len(esc) == 1
    assert led._s.get_payload(esc[0].payload_hash)["to"] == "strong-model"
    # the escalation result was witnessed and then passed validation
    t1 = [r for r in _payloads(led, "result") if r.get("id") == "T1"]
    assert t1[-1]["output"] == "good"
    assert t1[-1]["model"] == "strong-model"
    assert _payloads(led, "verdict")[-1]["ok"] is True
    assert led.verify(deep=True) is True


def test_without_escalation_the_failure_stands():
    led = _led()
    asyncio.run(_orch(led).submit("build the api"))  # no escalation executors
    assert led.query(kind="tier_escalation") == []
    assert _payloads(led, "verdict")[-1]["ok"] is False
    assert led.verify(deep=True) is True


def test_result_entries_record_model_identity():
    led = _led()
    asyncio.run(_orch(led, escalation=[_Strong()]).submit("build the api"))
    models = {r["model"] for r in _payloads(led, "result") if "model" in r}
    assert "strong-model" in models   # the escalation model is recorded
    assert "_Base" in models          # the base executor's identity (its type name) is recorded


def test_escalation_walks_a_two_rung_ladder():
    led = _led()
    ladder = [_Fixed("bad", "mid-model"), _Fixed("good", "frontier-model")]
    asyncio.run(_orch(led, escalation=ladder).submit("build the api"))
    # rung 1 still fails ("bad"), rung 2 passes ("good"): both escalations witnessed in order
    tos = [led._s.get_payload(e.payload_hash)["to"] for e in led.query(kind="tier_escalation")]
    assert tos == ["mid-model", "frontier-model"]
    t1 = [r for r in _payloads(led, "result") if r.get("id") == "T1"]
    assert t1[-1]["output"] == "good" and t1[-1]["model"] == "frontier-model"
    assert _payloads(led, "verdict")[-1]["ok"] is True
    assert led.verify(deep=True) is True


def test_budget_stops_escalation_before_it_runs():
    # plan(1) + task(2) + validate-fail(3) spends a 3-call budget; the failed task
    # must NOT escalate (a model call past the ceiling), so no tier_escalation is witnessed.
    led = _led()
    asyncio.run(_orch(led, escalation=[_Strong()]).submit("build the api", budget=RunBudget(max_model_calls=3)))
    assert led.query(kind="tier_escalation") == []
    assert led.verify(deep=True) is True
