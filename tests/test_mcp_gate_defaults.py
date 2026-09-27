"""An embedded MCP surface starts without the gate decision tools, and gate errors
use the closed error shape.

Falsifiers for review findings F11 and F12. On the first 1.15.0 candidate the
McpSurface constructor defaulted the grant to on, so a Python embedder handed a
connected model the tools to approve its own gates; and a decision for an unknown
gate came back as free text with no ``structuredContent``.
"""
import asyncio
import inspect

from forum.daemon import build_orchestrator
from forum.gates import GatePolicy
from forum.mcp_surface import McpSurface
from forum.plan import Plan, Task

GATE_TOOLS = {"gate_approve", "gate_edit", "gate_reject"}
CLOSED_KEYS = {"code", "retryable", "setup", "detail"}


def _granted(orch):
    params = inspect.signature(McpSurface.__init__).parameters
    if "allow_gate_decisions" in params:
        return McpSurface(orch, allow_gate_decisions=True)
    return McpSurface(orch)


def _call(surface, name, arguments):
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": name, "arguments": arguments}}
    return asyncio.run(surface.handle(msg))["result"]


def test_an_embedded_mcp_surface_lists_no_gate_decision_tools_by_default(tmp_path):
    surface = McpSurface(build_orchestrator(str(tmp_path / "ledger")))
    resp = asyncio.run(surface.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))
    names = {t["name"] for t in resp["result"]["tools"]}
    assert not names & GATE_TOOLS
    assert "gate_list" in names  # reading the open gates needs no grant


def test_an_embedded_mcp_surface_refuses_a_gate_decision_by_default(tmp_path):
    orch = build_orchestrator(str(tmp_path / "ledger"))
    asyncio.run(orch.submit_plan(Plan((Task("T1", "x", "deploy", ()),)),
                                 gates=GatePolicy(frozenset({0}))))
    run_seq = orch.ledger.get_payload(orch.ledger.query(kind="gate_pending")[0].payload_hash)["run_seq"]
    before = orch.ledger.count()
    result = _call(McpSurface(orch), "gate_approve", {"run_seq": run_seq, "wave": 0, "approver": "m"})
    assert result["isError"] is True
    assert (result.get("structuredContent") or {}).get("code") == "GRANT_REQUIRED"
    assert orch.ledger.count() == before


def test_an_unknown_gate_over_mcp_returns_the_closed_error_shape(tmp_path):
    result = _call(_granted(build_orchestrator(str(tmp_path / "ledger"))), "gate_approve",
                   {"run_seq": 99, "wave": 0, "approver": "p"})
    assert result["isError"] is True
    body = result.get("structuredContent") or {}
    assert set(body) == CLOSED_KEYS
    assert body["code"] == "NOT_FOUND"
    assert body["retryable"] is False


def test_an_invalid_gate_decision_over_mcp_returns_the_closed_error_shape(tmp_path):
    result = _call(_granted(build_orchestrator(str(tmp_path / "ledger"))), "gate_approve",
                   {"run_seq": "one", "wave": 0, "approver": "p"})
    assert result["isError"] is True
    body = result.get("structuredContent") or {}
    assert set(body) == CLOSED_KEYS
    assert body["code"] == "INVALID_ARGUMENT"


def test_an_edit_outside_the_gated_wave_over_mcp_is_refused_in_the_closed_shape(tmp_path):
    orch = build_orchestrator(str(tmp_path / "ledger"))
    plan = Plan((Task("T1", "x", "draft", ()), Task("T2", "x", "publish", ("T1",))))
    asyncio.run(orch.submit_plan(plan, gates=GatePolicy(frozenset({0, 1}))))
    run_seq = orch.ledger.get_payload(orch.ledger.query(kind="gate_pending")[0].payload_hash)["run_seq"]
    before = orch.ledger.count()
    result = _call(_granted(orch), "gate_edit", {"run_seq": run_seq, "wave": 0, "approver": "m",
                                                 "edits": {"T2": "publish now"}})
    assert result["isError"] is True
    assert (result.get("structuredContent") or {}).get("code") == "INVALID_ARGUMENT"
    assert orch.ledger.count() == before
