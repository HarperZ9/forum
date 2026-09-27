"""A decision made with a verified token outranks any decision a caller only asserted.

Falsifier for review finding F4. On 1.14.0 and the first 1.15.0 candidate the
latest decision won whoever made it: a person rejected a gate over authenticated
HTTP, and a later approval sent by a connected model (asserted, no token) ran the
wave anyway.
"""
import asyncio
import inspect
import json

from forum.auth import HmacVerifier, issue_hs256
from forum.daemon import build_orchestrator
from forum.gates import GatePolicy, gate_resolution, resolve_gate
from forum.http_surface import HttpSurface
from forum.ledger import InMemoryStorage, Ledger
from forum.mcp_surface import McpSurface
from forum.plan import Plan, Task

G = GatePolicy(frozenset({0}))
SECRET = "s" * 32


def _mcp(orch):
    params = inspect.signature(McpSurface.__init__).parameters
    if "allow_gate_decisions" in params:
        return McpSurface(orch, allow_gate_decisions=True)
    return McpSurface(orch)


def _paused(tmp_path):
    orch = build_orchestrator(str(tmp_path / "ledger"))
    plan = Plan((Task("T1", "x", "deploy to production", ()),))
    asyncio.run(orch.submit_plan(plan, gates=G))
    pend = orch.ledger.get_payload(orch.ledger.query(kind="gate_pending")[0].payload_hash)
    return orch, plan, pend["run_seq"]


def _http(orch, action, run_seq, token, **extra):
    body = {"run_seq": run_seq, "wave": 0, "approver": "alice", **extra}
    return asyncio.run(HttpSurface(orch, verifier=HmacVerifier(SECRET)).dispatch(
        "POST", f"/gate/{action}", json.dumps(body).encode(), f"Bearer {token}"))


def _token(subject="alice"):
    return issue_hs256(subject=subject, roles=["operator"], secret=SECRET, ttl_seconds=None)


def test_an_asserted_approval_cannot_reverse_an_authenticated_rejection(tmp_path):
    orch, plan, run_seq = _paused(tmp_path)
    assert _http(orch, "reject", run_seq, _token(), reason="not today").status == 200
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "gate_approve", "arguments": {"run_seq": run_seq, "wave": 0, "approver": "alice"}}}
    asyncio.run(_mcp(orch).handle(call))
    results = asyncio.run(orch.submit_plan(plan, resume=True, gates=G))
    assert "T1" not in results
    assert gate_resolution(orch.ledger, run_seq, 0) == "rejected"


def test_an_asserted_edit_cannot_replace_an_authenticated_edit(tmp_path):
    orch, plan, run_seq = _paused(tmp_path)
    assert _http(orch, "edit", run_seq, _token(), edits={"T1": "deploy to staging"}).status == 200
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "gate_edit", "arguments": {"run_seq": run_seq, "wave": 0, "approver": "alice",
                                           "edits": {"T1": "deploy to production now"}}}}
    asyncio.run(_mcp(orch).handle(call))
    results = asyncio.run(orch.submit_plan(plan, resume=True, gates=G))
    assert results["T1"].output == "done: deploy to staging"


def test_an_authenticated_person_can_still_change_their_mind(tmp_path):
    orch, plan, run_seq = _paused(tmp_path)
    assert _http(orch, "reject", run_seq, _token(), reason="not yet").status == 200
    assert _http(orch, "approve", run_seq, _token()).status == 200
    results = asyncio.run(orch.submit_plan(plan, resume=True, gates=G))
    assert results["T1"].output == "done: deploy to production"


def test_an_authenticated_rejection_outranks_an_earlier_asserted_approval():
    ticks = iter(float(t) for t in range(1, 1000))
    led = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    plan = led.append(actor="dispatch", kind="plan", payload={"waves": [["T1"]], "edges": []})
    led.append(actor="dispatch", kind="gate_pending",
               payload={"run_seq": plan.seq, "wave": 0, "tasks": ["T1"], "question": "q",
                        "requested_by": "dispatch"}, causal_parent=plan.seq)
    sourced = "approver_source" in inspect.signature(resolve_gate).parameters
    authenticated = {"approver_source": "authenticated"} if sourced else {}
    resolve_gate(led, plan.seq, 0, "gate_approved", approver="model")
    resolve_gate(led, plan.seq, 0, "gate_rejected", approver="alice", **authenticated)
    resolve_gate(led, plan.seq, 0, "gate_approved", approver="model")
    assert gate_resolution(led, plan.seq, 0) == "rejected"
