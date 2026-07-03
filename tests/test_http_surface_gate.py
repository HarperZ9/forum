import asyncio
import json

from forum.engine import Orchestrator
from forum.executor import EchoExecutor
from forum.gates import gate_edits, gate_resolution
from forum.http_surface import HttpSurface
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.roster import load_default

ALL = frozenset({"engineering", "graphics", "support", "research"})


def _surface():
    ticks = iter(float(t) for t in range(1, 100_000))
    ledger = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        load_default(), ledger, EchoExecutor(),
        Policy(allowed_categories=ALL, max_parallel=4),
    )
    return HttpSurface(orch), orch


def _seed_pending(led):
    req = led.append(actor="client", kind="request", payload={"tasks": ["T1", "T2"]})
    plan = led.append(
        actor="dispatch", kind="plan", payload={"waves": [["T1"], ["T2"]], "edges": []},
        causal_parent=req.seq,
    )
    led.append(
        actor="dispatch", kind="gate_pending",
        payload={"run_seq": plan.seq, "wave": 1, "tasks": ["T2"], "question": "approve?", "requested_by": "dispatch"},
        causal_parent=plan.seq,
    )
    return plan.seq


def _do(surface, method, path, body=b""):
    return asyncio.run(surface.dispatch(method, path, body))


def test_get_gates_lists_pending():
    surface, orch = _surface()
    run_seq = _seed_pending(orch.ledger)
    resp = _do(surface, "GET", "/gates")
    assert resp.status == 200
    data = json.loads(resp.body)
    assert data["pending"][0]["run_seq"] == run_seq
    assert data["pending"][0]["wave"] == 1


def test_get_gates_surfaces_deadline():
    surface, orch = _surface()
    led = orch.ledger
    req = led.append(actor="client", kind="request", payload={"tasks": ["T1", "T2"]})
    plan = led.append(
        actor="dispatch", kind="plan", payload={"waves": [["T1"], ["T2"]], "edges": []},
        causal_parent=req.seq,
    )
    led.append(
        actor="dispatch", kind="gate_pending",
        payload={
            "run_seq": plan.seq, "wave": 1, "tasks": ["T2"], "question": "ship?",
            "requested_by": "dispatch", "deadline": 9999.0, "on_expiry": "reject",
        },
        causal_parent=plan.seq,
    )
    data = json.loads(_do(surface, "GET", "/gates").body)
    assert data["pending"][0]["deadline"] == 9999.0
    assert data["pending"][0]["on_expiry"] == "reject"


def test_post_gate_approve_resolves():
    surface, orch = _surface()
    run_seq = _seed_pending(orch.ledger)
    body = json.dumps({"run_seq": run_seq, "wave": 1, "approver": "op", "note": "ok"}).encode()
    resp = _do(surface, "POST", "/gate/approve", body)
    assert resp.status == 200
    assert gate_resolution(orch.ledger, run_seq, 1) == "approved"


def test_post_gate_reject_resolves():
    surface, orch = _surface()
    run_seq = _seed_pending(orch.ledger)
    body = json.dumps({"run_seq": run_seq, "wave": 1, "approver": "op", "reason": "unsafe"}).encode()
    resp = _do(surface, "POST", "/gate/reject", body)
    assert resp.status == 200
    assert gate_resolution(orch.ledger, run_seq, 1) == "rejected"


def test_post_gate_edit_resolves_with_edits():
    surface, orch = _surface()
    run_seq = _seed_pending(orch.ledger)
    body = json.dumps({"run_seq": run_seq, "wave": 1, "approver": "op", "edits": {"T2": "NEW"}}).encode()
    resp = _do(surface, "POST", "/gate/edit", body)
    assert resp.status == 200
    assert gate_resolution(orch.ledger, run_seq, 1) == "edited"
    assert gate_edits(orch.ledger, run_seq, 1) == {"T2": "NEW"}


def test_gate_approve_missing_field_is_400():
    surface, _ = _surface()
    resp = _do(surface, "POST", "/gate/approve", json.dumps({"wave": 1, "approver": "op"}).encode())
    assert resp.status == 400


def test_gate_edit_without_edits_is_400():
    surface, orch = _surface()
    run_seq = _seed_pending(orch.ledger)
    resp = _do(surface, "POST", "/gate/edit", json.dumps({"run_seq": run_seq, "wave": 1, "approver": "op"}).encode())
    assert resp.status == 400
