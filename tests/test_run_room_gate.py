from forum.ledger import InMemoryStorage, Ledger
from forum.run_room import build_run_room


def _ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _seed_pending_gate(led):
    req = led.append(actor="client", kind="request", payload={"text": "build and deploy"})
    plan = led.append(
        actor="dispatch", kind="plan", payload={"waves": [["T1"], ["T2"]], "edges": []},
        causal_parent=req.seq,
    )
    led.append(
        actor="dispatch", kind="gate_pending",
        payload={"run_seq": plan.seq, "wave": 1, "tasks": ["T2"], "question": "approve deploy?", "requested_by": "dispatch"},
        causal_parent=plan.seq,
    )
    return plan.seq


def test_run_room_signals_pending_gates_count():
    led = _ledger()
    _seed_pending_gate(led)
    room = build_run_room(led)
    assert room["signals"]["pending_gates"] == 1


def test_run_room_surfaces_a_review_gate_next_action():
    led = _ledger()
    run_seq = _seed_pending_gate(led)
    room = build_run_room(led)
    gate_actions = [a for a in room["next_actions"] if a["kind"] == "review_gate"]
    assert len(gate_actions) == 1
    assert gate_actions[0]["priority"] == "high"
    assert gate_actions[0]["target"] == {"run_seq": run_seq, "wave": 1}


def test_resolved_gate_is_not_pending():
    led = _ledger()
    run_seq = _seed_pending_gate(led)
    pend = led.query(kind="gate_pending")[0]
    led.append(
        actor="operator", kind="gate_approved",
        payload={"run_seq": run_seq, "wave": 1, "approver": "op", "note": ""},
        causal_parent=pend.seq,
    )
    room = build_run_room(led)
    assert room["signals"]["pending_gates"] == 0
    assert all(a["kind"] != "review_gate" for a in room["next_actions"])
