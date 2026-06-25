import asyncio

from forum.engine import Orchestrator
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.report import compare, summarize
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


class _Exec:
    async def run(self, a):
        agent = a.agent
        if agent == "coordinator":
            return Result(a.task_id, agent, '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build", "depends_on": []}]}')
        if agent == "validator":
            return Result(a.task_id, agent, '{"ok": true, "score": 0.9, "reason": "ok"}')
        if agent == "synthesizer":
            return Result(a.task_id, agent, "final")
        return Result(a.task_id, agent, "did it")


def _led():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _run(led):
    orch = Orchestrator(ROSTER, led, _Exec(), Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2))
    asyncio.run(orch.submit("build the api"))


def test_get_payload_public_accessor():
    led = _led()
    e = led.append(actor="x", kind="k", payload={"v": 1})
    assert led.get_payload(e.payload_hash) == {"v": 1}


def test_summarize_counts_a_witnessed_run():
    led = _led()
    _run(led)
    s = summarize(led)
    assert s["requests"] == 1
    assert s["tasks"] == 1
    assert s["task_results"] == 1
    assert s["failed_results"] == 0
    assert s["verdicts_pass"] == 1 and s["verdicts_fail"] == 0
    assert s["answers"] == 1
    assert s["escalations"] == 0
    assert s["model_calls"] == {"_Exec": 1}   # the executor's identity, seen through the counter
    assert s["verified"] is True
    assert len(s["checkpoint"]) == 64


def test_compare_two_runs_reports_deltas():
    a_led, b_led = _led(), _led()
    _run(a_led)
    _run(b_led)
    _run(b_led)  # b has two runs
    delta = compare(summarize(a_led), summarize(b_led))
    assert delta["requests"] == 1          # b has one more request than a
    assert delta["task_results"] == 1
    assert delta["answers"] == 1
