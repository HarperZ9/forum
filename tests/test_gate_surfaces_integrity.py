"""Gate decisions through the CLI, HTTP and MCP: unknown gates, the launch grant, the approver.

Each test here failed on forum-engine 1.14.0.
"""
import asyncio
import io
import json

import pytest

from forum.auth import HmacVerifier, issue_hs256
from forum.cli import main
from forum.engine import Orchestrator
from forum.executor import EchoExecutor
from forum.http_surface import HttpSurface
from forum.ledger import InMemoryStorage, Ledger
from forum.mcp_surface import McpSurface
from forum.policy import Policy
from forum.roster import load_default
from forum.storage import FileStorage

ALL = frozenset({"engineering", "graphics", "support", "research"})
WRITE_TOOLS = ("gate_approve", "gate_edit", "gate_reject")
ALIASES = ("forum.gate.approve", "forum.gate.edit", "forum.gate.reject")
ARGS = {
    "gate_approve": {"approver": "op"},
    "gate_edit": {"approver": "op", "edits": {"T2": "NEW"}},
    "gate_reject": {"approver": "op", "reason": "no"},
}


def _orch():
    ticks = iter(float(t) for t in range(1, 100_000))
    return Orchestrator(
        load_default(),
        Ledger(InMemoryStorage(), clock=lambda: next(ticks)),
        EchoExecutor(),
        Policy(allowed_categories=ALL, max_parallel=4),
    )


def _seed_pending(led):
    req = led.append(actor="client", kind="request", payload={"tasks": ["T1", "T2"]})
    plan = led.append(
        actor="dispatch", kind="plan", payload={"waves": [["T1"], ["T2"]], "edges": []},
        causal_parent=req.seq,
    )
    led.append(
        actor="dispatch", kind="gate_pending",
        payload={"run_seq": plan.seq, "wave": 1, "tasks": ["T2"], "question": "approve?",
                 "requested_by": "dispatch"},
        causal_parent=plan.seq,
    )
    return plan.seq


def _call(surface, name, arguments):
    msg = {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
           "params": {"name": name, "arguments": arguments}}
    return asyncio.run(surface.handle(msg))


def _listed(surface):
    resp = asyncio.run(surface.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))
    return {t["name"] for t in resp["result"]["tools"]}


def _error(resp):
    result = resp["result"]
    assert result["isError"] is True
    return json.loads(result["content"][0]["text"])


# --- unknown gates -----------------------------------------------------------


@pytest.mark.parametrize("tool", WRITE_TOOLS)
def test_mcp_decision_on_an_unknown_gate_is_not_found_and_appends_nothing(tool):
    orch = _orch()
    run_seq = _seed_pending(orch.ledger)
    before = orch.ledger.count()
    resp = _call(McpSurface(orch, allow_gate_decisions=True), tool,
                 {"run_seq": run_seq + 50, "wave": 1, **ARGS[tool]})
    assert _error(resp)["code"] == "NOT_FOUND"
    assert orch.ledger.count() == before


def test_mcp_decision_on_the_right_run_but_wrong_wave_is_not_found():
    orch = _orch()
    run_seq = _seed_pending(orch.ledger)
    before = orch.ledger.count()
    resp = _call(McpSurface(orch, allow_gate_decisions=True), "gate_approve",
                 {"run_seq": run_seq, "wave": 0, "approver": "op"})
    assert _error(resp)["code"] == "NOT_FOUND"
    assert orch.ledger.count() == before


def test_http_decision_on_an_unknown_gate_is_404_and_appends_nothing():
    orch = _orch()
    before = orch.ledger.count()
    body = json.dumps({"run_seq": 12345, "wave": 0, "approver": "op"}).encode()
    resp = asyncio.run(HttpSurface(orch).dispatch("POST", "/gate/approve", body))
    assert resp.status == 404
    assert json.loads(resp.body)["code"] == "NOT_FOUND"
    assert orch.ledger.count() == before


def test_cli_decision_on_an_unknown_gate_fails_and_appends_nothing(tmp_path, capsys):
    d = str(tmp_path / "led")
    run_seq = _seed_pending(Ledger(FileStorage(d)))
    rc = main(["gate", "approve", "--ledger", d, "--run-seq", str(run_seq + 9), "--wave", "1",
               "--approver", "op"])
    assert rc == 1
    assert "no gate is pending" in capsys.readouterr().err
    assert Ledger(FileStorage(d)).count() == 3


# --- the launch grant ------------------------------------------------------


def test_without_the_grant_tools_list_has_no_gate_write_tools():
    names = _listed(McpSurface(_orch(), allow_gate_decisions=False))
    assert "gate_list" in names
    assert not names.intersection(WRITE_TOOLS)


@pytest.mark.parametrize("tool", WRITE_TOOLS + ALIASES)
def test_without_the_grant_a_direct_call_is_grant_required_and_appends_nothing(tool):
    orch = _orch()
    run_seq = _seed_pending(orch.ledger)
    before = orch.ledger.count()
    canonical = tool.replace("forum.gate.", "gate_")
    resp = _call(McpSurface(orch, allow_gate_decisions=False), tool,
                 {"run_seq": run_seq, "wave": 1, **ARGS[canonical]})
    err = _error(resp)
    assert err["code"] == "GRANT_REQUIRED"
    assert err["setup"] == "ALLOW_GATE_DECISIONS"
    assert err["retryable"] is False
    assert resp["result"]["structuredContent"] == err
    assert orch.ledger.count() == before


def test_forum_mcp_starts_without_the_grant_unless_the_launch_names_it(tmp_path, monkeypatch):
    import forum.mcp_surface as mcp_surface

    seen = []

    async def fake_serve(orchestrator=None, ledger_dir="forum-ledger", **kwargs):
        seen.append(kwargs.get("allow_gate_decisions"))

    monkeypatch.setattr(mcp_surface, "serve_stdio", fake_serve)
    assert main(["mcp", "--ledger", str(tmp_path / "a")]) == 0
    assert main(["mcp", "--ledger", str(tmp_path / "b"), "--allow-gate-decisions"]) == 0
    assert seen == [False, True]


def test_serve_stdio_by_default_lists_no_gate_write_tools(tmp_path, monkeypatch, capsys):
    from forum.daemon import build_orchestrator
    from forum.mcp_surface import serve_stdio

    line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(line))
    asyncio.run(serve_stdio(build_orchestrator(str(tmp_path / "led"))))
    names = {t["name"] for t in json.loads(capsys.readouterr().out)["result"]["tools"]}
    assert "gate_list" in names
    assert not names.intersection(WRITE_TOOLS)


# --- who approved ----------------------------------------------------------


def _last_decision(led):
    entry = led.query(kind="gate_approved")[-1]
    return led.get_payload(entry.payload_hash)


def test_mcp_and_cli_mark_the_approver_as_asserted(tmp_path):
    orch = _orch()
    run_seq = _seed_pending(orch.ledger)
    _call(McpSurface(orch, allow_gate_decisions=True), "gate_approve",
          {"run_seq": run_seq, "wave": 1, "approver": "someone"})
    body = _last_decision(orch.ledger)
    assert body["approver"] == "someone"
    assert body["approver_source"] == "asserted"

    d = str(tmp_path / "led")
    run_seq = _seed_pending(Ledger(FileStorage(d)))
    assert main(["gate", "approve", "--ledger", d, "--run-seq", str(run_seq), "--wave", "1",
                 "--approver", "someone"]) == 0
    assert _last_decision(Ledger(FileStorage(d)))["approver_source"] == "asserted"


def test_http_with_auth_records_the_token_subject_as_the_approver():
    orch = _orch()
    run_seq = _seed_pending(orch.ledger)
    secret = "s3cret-for-tests"
    surface = HttpSurface(orch, verifier=HmacVerifier(secret, clock=lambda: 1000.0))
    token = issue_hs256(subject="alice", roles=["approver"], secret=secret, clock=lambda: 1000.0)
    body = json.dumps({"run_seq": run_seq, "wave": 1, "approver": "bob"}).encode()
    resp = asyncio.run(surface.dispatch("POST", "/gate/approve", body, f"Bearer {token}"))
    assert resp.status == 200
    decision = _last_decision(orch.ledger)
    assert decision["approver"] == "alice"
    assert decision["approver_source"] == "authenticated"
    assert decision["asserted_approver"] == "bob"


def test_http_with_auth_needs_no_approver_field():
    orch = _orch()
    run_seq = _seed_pending(orch.ledger)
    secret = "s3cret-for-tests"
    surface = HttpSurface(orch, verifier=HmacVerifier(secret, clock=lambda: 1000.0))
    token = issue_hs256(subject="alice", roles=["approver"], secret=secret, clock=lambda: 1000.0)
    body = json.dumps({"run_seq": run_seq, "wave": 1}).encode()
    resp = asyncio.run(surface.dispatch("POST", "/gate/approve", body, f"Bearer {token}"))
    assert resp.status == 200
    decision = _last_decision(orch.ledger)
    assert decision["approver"] == "alice"
    assert "asserted_approver" not in decision
