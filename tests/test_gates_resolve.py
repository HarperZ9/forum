from forum.gates import gate_edits, gate_resolution, resolve_gate
from forum.ledger import InMemoryStorage, Ledger


def _ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _seed_pending(led, wave=1):
    req = led.append(actor="client", kind="request", payload={"tasks": ["T1", "T2"]})
    plan = led.append(
        actor="dispatch", kind="plan", payload={"waves": [["T1"], ["T2"]], "edges": []},
        causal_parent=req.seq,
    )
    pend = led.append(
        actor="dispatch", kind="gate_pending",
        payload={"run_seq": plan.seq, "wave": wave, "tasks": ["T2"], "question": "q", "requested_by": "dispatch"},
        causal_parent=plan.seq,
    )
    return plan.seq, pend.seq


def test_resolve_gate_approve_chains_to_pending_and_verifies():
    led = _ledger()
    run_seq, pend_seq = _seed_pending(led)
    entry = resolve_gate(led, run_seq, 1, "gate_approved", approver="op", note="looks good")
    assert entry.kind == "gate_approved"
    assert entry.causal_parent == pend_seq  # chained to the pending gate it resolves
    assert gate_resolution(led, run_seq, 1) == "approved"
    body = led.get_payload(entry.payload_hash)
    assert body == {"run_seq": run_seq, "wave": 1, "approver": "op", "note": "looks good"}
    assert led.verify(deep=True) is True


def test_resolve_gate_reject_records_reason():
    led = _ledger()
    run_seq, pend_seq = _seed_pending(led)
    entry = resolve_gate(led, run_seq, 1, "gate_rejected", approver="op", reason="unsafe")
    assert entry.causal_parent == pend_seq
    assert gate_resolution(led, run_seq, 1) == "rejected"
    assert led.get_payload(entry.payload_hash)["reason"] == "unsafe"
    assert led.verify(deep=True) is True


def test_resolve_gate_edit_carries_edits():
    led = _ledger()
    run_seq, _ = _seed_pending(led)
    resolve_gate(led, run_seq, 1, "gate_edited", approver="op", edits={"T2": "NEW"}, note="tweaked")
    assert gate_resolution(led, run_seq, 1) == "edited"
    assert gate_edits(led, run_seq, 1) == {"T2": "NEW"}
    assert led.verify(deep=True) is True


def test_resolve_gate_rejects_unknown_kind():
    led = _ledger()
    run_seq, _ = _seed_pending(led)
    try:
        resolve_gate(led, run_seq, 1, "gate_bogus", approver="op")
    except ValueError as exc:
        assert "unknown gate decision kind" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown kind")


def test_resolve_gate_chains_to_run_seq_when_no_pending():
    led = _ledger()
    req = led.append(actor="client", kind="request", payload={"tasks": ["T1"]})
    plan = led.append(
        actor="dispatch", kind="plan", payload={"waves": [["T1"]], "edges": []},
        causal_parent=req.seq,
    )
    entry = resolve_gate(led, plan.seq, 1, "gate_approved", approver="op")
    assert entry.causal_parent == plan.seq  # falls back to run_seq when no pending exists
    assert led.verify(deep=True) is True
