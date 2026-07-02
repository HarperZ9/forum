import asyncio
import json

from forum.engine import Orchestrator
from forum.executor import EchoExecutor
from forum.gates import gate_edits, gate_resolution
from forum.http_surface import HttpSurface
from forum.ledger import InMemoryStorage, Ledger
from forum.mcp_surface import McpSurface
from forum.policy import Policy
from forum.roster import load_default

ALL = frozenset({"engineering", "graphics", "support", "research"})


def _orch():
    ticks = iter(float(t) for t in range(1, 100_000))
    orch = Orchestrator(
        load_default(),
        Ledger(InMemoryStorage(), clock=lambda: next(ticks)),
        EchoExecutor(),
        Policy(allowed_categories=ALL, max_parallel=4),
    )
    return orch


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


def _call(surface, name, arguments=None):
    msg = {
        "jsonrpc": "2.0", "id": 9, "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }
    return asyncio.run(surface.handle(msg))


def _text(resp):
    return json.loads(resp["result"]["content"][0]["text"])


def test_gate_list_tool_lists_pending():
    orch = _orch()
    run_seq = _seed_pending(orch.ledger)
    resp = _call(McpSurface(orch), "gate_list")
    assert resp["result"]["isError"] is False
    assert _text(resp)["pending"][0]["run_seq"] == run_seq


def test_gate_approve_tool_resolves():
    orch = _orch()
    run_seq = _seed_pending(orch.ledger)
    resp = _call(McpSurface(orch), "gate_approve", {"run_seq": run_seq, "wave": 1, "approver": "op"})
    assert resp["result"]["isError"] is False
    assert gate_resolution(orch.ledger, run_seq, 1) == "approved"


def test_gate_edit_tool_resolves_with_edits():
    orch = _orch()
    run_seq = _seed_pending(orch.ledger)
    resp = _call(McpSurface(orch), "gate_edit", {"run_seq": run_seq, "wave": 1, "approver": "op", "edits": {"T2": "NEW"}})
    assert resp["result"]["isError"] is False
    assert gate_edits(orch.ledger, run_seq, 1) == {"T2": "NEW"}


def test_gate_reject_tool_resolves():
    orch = _orch()
    run_seq = _seed_pending(orch.ledger)
    resp = _call(McpSurface(orch), "gate_reject", {"run_seq": run_seq, "wave": 1, "approver": "op", "reason": "no"})
    assert gate_resolution(orch.ledger, run_seq, 1) == "rejected"


def test_gate_tools_are_advertised():
    orch = _orch()
    resp = asyncio.run(McpSurface(orch).handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}))
    names = {t["name"] for t in resp["result"]["tools"]}
    assert {"gate_list", "gate_approve", "gate_edit", "gate_reject"} <= names


def test_mcp_and_http_gate_approve_parity():
    """The MCP gate_approve routes through the same HttpSurface path as HTTP."""
    orch_http = _orch()
    run_seq_h = _seed_pending(orch_http.ledger)
    http = HttpSurface(orch_http)
    resp_http = asyncio.run(
        http.dispatch("POST", "/gate/approve", json.dumps({"run_seq": run_seq_h, "wave": 1, "approver": "op"}).encode())
    )

    orch_mcp = _orch()
    run_seq_m = _seed_pending(orch_mcp.ledger)
    resp_mcp = _call(McpSurface(orch_mcp), "gate_approve", {"run_seq": run_seq_m, "wave": 1, "approver": "op"})

    assert resp_http.status == 200
    assert resp_mcp["result"]["isError"] is False
    assert gate_resolution(orch_http.ledger, run_seq_h, 1) == "approved"
    assert gate_resolution(orch_mcp.ledger, run_seq_m, 1) == "approved"
