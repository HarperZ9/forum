import asyncio

from forum.engine import Orchestrator
from forum.executor import EchoExecutor
from forum.gates import GatePolicy, gate_resolution, resolve_gate
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task
from forum.policy import Policy
from forum.roster import load_default

ALL = frozenset({"engineering", "graphics", "support", "research"})


def _orch():
    ticks = iter(float(t) for t in range(1, 100_000))
    return Orchestrator(
        load_default(),
        Ledger(InMemoryStorage(), clock=lambda: next(ticks)),
        EchoExecutor(),
        Policy(allowed_categories=ALL, max_parallel=4),
    )


def _result_ids(led):
    return {led.get_payload(e.payload_hash).get("id") for e in led.query(kind="result")}


def test_submit_plan_pauses_at_gate_then_resumes_on_approval():
    orch = _orch()
    led = orch.ledger
    plan = Plan((Task("T1", "backend", "a", ()), Task("T2", "backend", "b", ("T1",))))

    # first submit: gate on wave 1 pauses before T2
    asyncio.run(orch.submit_plan(plan, gates=GatePolicy(frozenset({1}), "approve?")))
    assert "T1" in _result_ids(led)
    assert "T2" not in _result_ids(led)
    run_seq = led.query(kind="plan")[0].seq
    assert gate_resolution(led, run_seq, 1) == "pending"

    # operator approves, then re-submits with resume=True over the same ledger
    resolve_gate(led, run_seq, 1, "gate_approved", approver="op")
    results = asyncio.run(orch.submit_plan(plan, resume=True, gates=GatePolicy(frozenset({1}))))
    assert results["T2"].ok is True
    assert "T2" in _result_ids(led)
    assert led.verify(deep=True) is True
