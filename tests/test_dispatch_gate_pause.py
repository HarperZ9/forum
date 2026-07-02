import asyncio

from forum.dispatch import dispatch_plan
from forum.executor import EchoExecutor
from forum.gates import GatePolicy, gate_resolution
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task


def make_ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _result_ids(ledger):
    return {
        ledger.get_payload(e.payload_hash).get("id")
        for e in ledger.query(kind="result")
    }


def test_gate_pauses_run_and_blocks_downstream_wave():
    """CAN-IT-FAIL: a gate on wave 1 must stop the loop so T2 never runs.

    If the gate did NOT stop the loop, T2 would have a witnessed result and the
    returned dict would carry it -> this test fails. The ledger is the source of
    truth for both assertions.
    """
    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))  # two waves

    results = asyncio.run(
        dispatch_plan(ledger=ledger, plan=plan, executor=EchoExecutor(), gates=GatePolicy(frozenset({1}), "approve?"))
    )

    # (a) a gate_pending for wave 1 exists, keyed to the plan entry
    plan_seq = ledger.query(kind="plan")[0].seq
    pendings = [ledger.get_payload(e.payload_hash) for e in ledger.query(kind="gate_pending")]
    assert any(p["run_seq"] == plan_seq and p["wave"] == 1 for p in pendings)
    pend = next(p for p in pendings if p["wave"] == 1)
    assert pend["tasks"] == ["T2"]
    assert pend["question"] == "approve?"

    # (b) the ledger has a result for T1 but NOT for T2 (downstream never dispatched)
    ids = _result_ids(ledger)
    assert "T1" in ids
    assert "T2" not in ids

    # (c) the returned results dict has no T2
    assert "T1" in results
    assert "T2" not in results

    # the run is blocked (pending), and the chain still verifies
    assert gate_resolution(ledger, plan_seq, 1) == "pending"
    assert ledger.verify(deep=True) is True


def test_no_gate_policy_runs_everything():
    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    results = asyncio.run(dispatch_plan(plan, ledger, EchoExecutor()))
    assert set(results) == {"T1", "T2"}
    assert ledger.query(kind="gate_pending") == []


def test_ungated_wave_zero_is_not_paused():
    """A GatePolicy that gates only wave 1 must let wave 0 run before pausing."""
    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    asyncio.run(
        dispatch_plan(plan, ledger, EchoExecutor(), gates=GatePolicy(frozenset({1})))
    )
    assert "T1" in _result_ids(ledger)  # wave 0 ran
    assert "T2" not in _result_ids(ledger)  # wave 1 gated
