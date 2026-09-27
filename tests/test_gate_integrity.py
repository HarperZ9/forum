"""A gate decision counts only for a gate that was raised and is still open.

Each test here failed on forum-engine 1.14.0: a decision recorded before the
gate opened, a decision from an earlier run, or an entry not chained to the
pending gate let a gated wave run with no pause.
"""
import asyncio

from forum.dispatch import dispatch_plan
from forum.executor import EchoExecutor
from forum.gates import GatePolicy, gate_edits, gate_resolution, resolve_gate
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task


def _ledger():
    ticks = iter(float(t) for t in range(1, 10_000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _result_ids(led):
    return [led.get_payload(e.payload_hash)["id"] for e in led.query(kind="result")]


def _pending_keys(led):
    out = []
    for e in led.query(kind="gate_pending"):
        body = led.get_payload(e.payload_hash)
        out.append((body["run_seq"], body["wave"]))
    return out


def _gated(ids, wave=0):
    tasks = tuple(Task(tid, "x", f"do {tid}", ()) for tid in ids)
    return Plan(tasks), GatePolicy(frozenset({wave}))


def test_a_decision_recorded_before_any_gate_leaves_the_gated_wave_paused():
    # The audit's acceptance test. The ledger is empty, so the next plan entry
    # will take seq 1: an approval for (run_seq=1, wave=0) written now targets
    # the run that is about to start.
    led = _ledger()
    resolve_gate(led, 1, 0, "gate_approved", approver="model")
    plan, gates = _gated(["T1"])

    results = asyncio.run(dispatch_plan(plan, led, EchoExecutor(), gates=gates))

    run_seq = led.query(kind="plan")[0].seq
    assert run_seq == 1  # the pre-recorded decision named exactly this run
    assert results == {}
    assert _result_ids(led) == []
    assert _pending_keys(led) == [(1, 0)]
    assert gate_resolution(led, 1, 0) == "pending"
    assert led.verify(deep=True) is True


def test_a_decision_for_an_earlier_plan_seq_does_not_open_a_later_run():
    # 1.14.0 keyed every run in a ledger to the FIRST plan entry's seq, so an
    # approval written against that seq opened every later gated run.
    led = _ledger()
    asyncio.run(dispatch_plan(Plan((Task("A1", "x", "warm up", ()),)), led, EchoExecutor()))
    first_plan = led.query(kind="plan")[0].seq
    resolve_gate(led, first_plan, 0, "gate_approved", approver="model")
    plan, gates = _gated(["T1"])

    results = asyncio.run(dispatch_plan(plan, led, EchoExecutor(), gates=gates))

    assert "T1" not in results
    assert "T1" not in _result_ids(led)
    assert len(_pending_keys(led)) == 1
    assert led.verify(deep=True) is True


def test_an_approval_from_an_earlier_run_does_not_carry_to_a_new_run():
    led = _ledger()
    plan1, gates = _gated(["T1"])
    asyncio.run(dispatch_plan(plan1, led, EchoExecutor(), gates=gates))
    (run1, wave), = _pending_keys(led)
    resolve_gate(led, run1, wave, "gate_approved", approver="op")
    asyncio.run(dispatch_plan(plan1, led, EchoExecutor(), resume=True, gates=gates))
    assert _result_ids(led) == ["T1"]

    plan2, _ = _gated(["U1"])
    results = asyncio.run(dispatch_plan(plan2, led, EchoExecutor(), gates=gates))

    assert "U1" not in results
    assert _result_ids(led) == ["T1"]
    keys = _pending_keys(led)
    assert len(keys) == 2
    assert keys[1][0] != run1  # the new run has its own gate, keyed to its own plan
    assert led.verify(deep=True) is True


def test_a_resume_keys_its_gates_to_its_own_run_not_the_first_one():
    led = _ledger()
    plan1, gates = _gated(["T1"])
    asyncio.run(dispatch_plan(plan1, led, EchoExecutor(), gates=gates))
    (run1, _), = _pending_keys(led)
    resolve_gate(led, run1, 0, "gate_approved", approver="op")
    asyncio.run(dispatch_plan(plan1, led, EchoExecutor(), resume=True, gates=gates))

    plan2, _ = _gated(["U1"])
    asyncio.run(dispatch_plan(plan2, led, EchoExecutor(), gates=gates))
    run2 = _pending_keys(led)[1][0]

    # a resume with no decision for run 2 stays paused, and raises no new gate
    asyncio.run(dispatch_plan(plan2, led, EchoExecutor(), resume=True, gates=gates))
    assert "U1" not in _result_ids(led)
    assert len(_pending_keys(led)) == 2

    # the person approves run 2's own gate; the next resume runs its wave
    resolve_gate(led, run2, 0, "gate_approved", approver="op")
    results = asyncio.run(dispatch_plan(plan2, led, EchoExecutor(), resume=True, gates=gates))
    assert results["U1"].ok is True
    assert _result_ids(led) == ["T1", "U1"]
    assert led.verify(deep=True) is True


def _seed_pending(led, wave=1):
    req = led.append(actor="client", kind="request", payload={"tasks": ["T1", "T2"]})
    plan = led.append(
        actor="dispatch", kind="plan", payload={"waves": [["T1"], ["T2"]], "edges": []},
        causal_parent=req.seq,
    )
    pend = led.append(
        actor="dispatch", kind="gate_pending",
        payload={"run_seq": plan.seq, "wave": wave, "tasks": ["T2"], "question": "q",
                 "requested_by": "dispatch"},
        causal_parent=plan.seq,
    )
    return plan.seq, pend.seq


def test_a_decision_not_chained_to_the_pending_gate_is_ignored():
    led = _ledger()
    run_seq, _ = _seed_pending(led)
    led.append(
        actor="operator", kind="gate_approved",
        payload={"run_seq": run_seq, "wave": 1, "approver": "forged", "note": ""},
        causal_parent=run_seq,
    )
    assert gate_resolution(led, run_seq, 1) == "pending"


def test_a_decision_written_before_the_gate_opened_is_ignored_even_if_it_names_the_pending_seq():
    # Predict both the plan seq and the gate_pending seq and chain to the latter
    # before it exists. The decision precedes the gate, so it cannot count.
    led = _ledger()
    led.append(
        actor="operator", kind="gate_approved",
        payload={"run_seq": 2, "wave": 1, "approver": "forged", "note": ""},
        causal_parent=3,
    )
    run_seq, pend_seq = _seed_pending(led)
    assert (run_seq, pend_seq) == (2, 3)
    assert gate_resolution(led, run_seq, 1) == "pending"


def test_a_forged_expiry_is_ignored():
    led = _ledger()
    run_seq, _ = _seed_pending(led)
    led.append(
        actor="dispatch", kind="gate_expired",
        payload={"run_seq": run_seq, "wave": 1, "decision": "approved", "on_expiry": "approve",
                 "deadline": 0.0},
        causal_parent=run_seq,
    )
    assert gate_resolution(led, run_seq, 1) == "pending"


def test_edits_come_only_from_a_decision_chained_to_the_gate():
    led = _ledger()
    run_seq, _ = _seed_pending(led)
    resolve_gate(led, run_seq, 1, "gate_edited", approver="op", edits={"T2": "REVIEWED"})
    led.append(
        actor="operator", kind="gate_edited",
        payload={"run_seq": run_seq, "wave": 1, "approver": "forged", "edits": {"T2": "INJECTED"},
                 "note": ""},
        causal_parent=run_seq,
    )
    assert gate_resolution(led, run_seq, 1) == "edited"
    assert gate_edits(led, run_seq, 1) == {"T2": "REVIEWED"}
