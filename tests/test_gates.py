from forum.gates import GatePolicy, gate_edits, gate_resolution
from forum.ledger import InMemoryStorage, Ledger


def _ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _seed_plan(led):
    req = led.append(actor="client", kind="request", payload={"tasks": ["T1", "T2"]})
    plan = led.append(
        actor="dispatch", kind="plan", payload={"waves": [["T1"], ["T2"]], "edges": []},
        causal_parent=req.seq,
    )
    return plan.seq


def test_gate_policy_holds_gated_waves_and_question():
    policy = GatePolicy(frozenset({1, 2}), "approve before deploying")
    assert 1 in policy.gated_waves
    assert 3 not in policy.gated_waves
    assert policy.question == "approve before deploying"


def test_no_gate_entries_means_no_resolution():
    led = _ledger()
    run_seq = _seed_plan(led)
    assert gate_resolution(led, run_seq, 1) is None
    assert gate_edits(led, run_seq, 1) == {}


def test_pending_without_decision_is_pending():
    led = _ledger()
    run_seq = _seed_plan(led)
    led.append(
        actor="dispatch", kind="gate_pending",
        payload={"run_seq": run_seq, "wave": 1, "tasks": ["T2"], "question": "q", "requested_by": "dispatch"},
        causal_parent=run_seq,
    )
    assert gate_resolution(led, run_seq, 1) == "pending"


def test_approved_resolution():
    led = _ledger()
    run_seq = _seed_plan(led)
    pend = led.append(
        actor="dispatch", kind="gate_pending",
        payload={"run_seq": run_seq, "wave": 1, "tasks": ["T2"], "question": "q", "requested_by": "dispatch"},
        causal_parent=run_seq,
    )
    led.append(
        actor="operator", kind="gate_approved",
        payload={"run_seq": run_seq, "wave": 1, "approver": "op", "note": "ok"},
        causal_parent=pend.seq,
    )
    assert gate_resolution(led, run_seq, 1) == "approved"


def test_rejected_resolution():
    led = _ledger()
    run_seq = _seed_plan(led)
    pend = led.append(
        actor="dispatch", kind="gate_pending",
        payload={"run_seq": run_seq, "wave": 1, "tasks": ["T2"], "question": "q", "requested_by": "dispatch"},
        causal_parent=run_seq,
    )
    led.append(
        actor="operator", kind="gate_rejected",
        payload={"run_seq": run_seq, "wave": 1, "approver": "op", "reason": "unsafe"},
        causal_parent=pend.seq,
    )
    assert gate_resolution(led, run_seq, 1) == "rejected"


def test_edited_resolution_and_edits():
    led = _ledger()
    run_seq = _seed_plan(led)
    pend = led.append(
        actor="dispatch", kind="gate_pending",
        payload={"run_seq": run_seq, "wave": 1, "tasks": ["T2"], "question": "q", "requested_by": "dispatch"},
        causal_parent=run_seq,
    )
    led.append(
        actor="operator", kind="gate_edited",
        payload={"run_seq": run_seq, "wave": 1, "approver": "op", "edits": {"T2": "NEW"}, "note": ""},
        causal_parent=pend.seq,
    )
    assert gate_resolution(led, run_seq, 1) == "edited"
    assert gate_edits(led, run_seq, 1) == {"T2": "NEW"}


def test_resolution_is_scoped_to_run_seq_and_wave():
    led = _ledger()
    run_seq = _seed_plan(led)
    led.append(
        actor="dispatch", kind="gate_pending",
        payload={"run_seq": run_seq, "wave": 1, "tasks": ["T2"], "question": "q", "requested_by": "dispatch"},
        causal_parent=run_seq,
    )
    # a decision for a different wave does not resolve wave 1
    assert gate_resolution(led, run_seq, 2) is None
    # a decision for a different run_seq does not resolve this run's wave 1
    assert gate_resolution(led, run_seq + 999, 1) is None
