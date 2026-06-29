import asyncio
import json

from forum.engine import Orchestrator
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.mcp_surface import McpSurface
from forum.policy import Policy
from forum.roster import load_default

ALL = frozenset({"engineering", "graphics", "support", "research"})


class ScriptedExecutor:
    async def run(self, assignment):
        agent = assignment.agent
        if agent == "coordinator":
            out = '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "x", "depends_on": []}]}'
        elif agent == "validator":
            out = '{"ok": true, "score": 0.9, "reason": "ok"}'
        elif agent == "synthesizer":
            out = "Done."
        else:
            out = "handled"
        return Result(assignment.task_id, assignment.agent, out)


def _mcp():
    ticks = iter(float(t) for t in range(1, 100_000))
    orch = Orchestrator(
        load_default(),
        Ledger(InMemoryStorage(), clock=lambda: next(ticks)),
        ScriptedExecutor(),
        Policy(allowed_categories=ALL, max_parallel=4),
    )
    return McpSurface(orch)


def _h(surface, message):
    return asyncio.run(surface.handle(message))


def _call(surface, name, arguments=None):
    msg = {
        "jsonrpc": "2.0", "id": 9, "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }
    return _h(surface, msg)


def test_initialize_announces_forum():
    resp = _h(_mcp(), {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "forum"
    assert "protocolVersion" in resp["result"]
    assert "tools" in resp["result"]["capabilities"]


def test_tools_list_has_the_tools():
    resp = _h(_mcp(), {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert {"submit", "route", "plan", "status", "verify", "ledger_get"} <= names
    assert {"forum.submit", "forum.route", "forum.status", "forum.doctor", "forum.ledger.summary", "forum.prose.humanize"} <= names
    for tool in resp["result"]["tools"]:
        assert tool["inputSchema"]["type"] == "object"


def test_call_route_decides_a_lane():
    resp = _call(_mcp(), "route", {"text": "build the api database server endpoint"})
    result = resp["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["decided"] == "backend"


def test_call_prefixed_route_decides_a_lane():
    resp = _call(_mcp(), "forum.route", {"text": "build the api database server endpoint"})
    result = resp["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["decided"] == "backend"


def test_call_prefixed_route_decides_model_foundry_lane():
    resp = _call(_mcp(), "forum.route", {
        "text": (
            "Build a model foundry self improving daemon with context envelopes, "
            "eval promotion, and receipt chained workflow."
        )
    })
    result = resp["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["decided"] == "model-foundry"
    assert payload["needs_escalation"] is False


def test_call_prefixed_humanize_simplifies_agent_prose():
    resp = _call(_mcp(), "forum.prose.humanize", {
        "text": "As an AI language model, prior to launch utilize the report in order to assist users."
    })
    result = resp["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["schema"] == "forum.prose-humanization/v1"
    assert payload["output"] == "Before launch use the report to help users."
    assert "facts were not independently checked" in payload["not_verified"]


def test_call_submit_answers_and_witnesses():
    resp = _call(_mcp(), "submit", {"request": "design an api"})
    result = resp["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert payload["answer"] == "Done."
    assert "checkpoint" in payload
    assert payload["receipt"]["schema"] == "project-telos.action-receipt/v1"
    assert payload["receipt"]["ledger"]["verified"] is True
    assert payload["receipt"]["verification"]["verdict"] == "MATCH"


def test_call_status_and_verify_after_submit():
    surface = _mcp()
    _call(surface, "submit", {"request": "design an api"})
    status = json.loads(_call(surface, "status")["result"]["content"][0]["text"])
    assert status["entries"] > 0
    verify = json.loads(_call(surface, "verify")["result"]["content"][0]["text"])
    assert verify == {"chain": True, "deep": True}


def test_call_prefixed_status_and_doctor_return_action_envelopes():
    status = json.loads(_call(_mcp(), "forum.status")["result"]["content"][0]["text"])
    assert status["schema"] == "project-telos.flagship-action/v1"
    assert status["tool"] == "forum"
    assert status["command"] == "status"
    assert status["native"]["role"] == "orchestration-routing"

    doctor = json.loads(_call(_mcp(), "forum.doctor")["result"]["content"][0]["text"])
    assert doctor["schema"] == "project-telos.flagship-action/v1"
    assert doctor["command"] == "doctor"
    assert doctor["native"]["checks"][0]["status"] == "MATCH"
    assert doctor["next_actions"][0]["tool"] == "index"

def test_call_prefixed_ledger_summary_after_submit():
    surface = _mcp()
    _call(surface, "forum.submit", {"request": "design an api"})
    summary = json.loads(_call(surface, "forum.ledger.summary")["result"]["content"][0]["text"])
    assert summary["entries"] > 0
    assert summary["verified"] is True
    assert summary["requests"] == 1


def test_call_ledger_get_returns_an_entry():
    surface = _mcp()
    _call(surface, "submit", {"request": "design an api"})
    entry = json.loads(_call(surface, "ledger_get", {"seq": 0})["result"]["content"][0]["text"])
    assert entry["kind"] == "request"


def test_tool_layer_error_is_reported_via_iserror():
    # A tool whose underlying HTTP call fails (no such ledger entry -> 404) is a
    # successful JSON-RPC result with isError true, not a protocol error.
    resp = _call(_mcp(), "ledger_get", {"seq": 999})
    assert resp["result"]["isError"] is True


def test_unknown_tool_is_a_jsonrpc_error():
    resp = _call(_mcp(), "nonesuch", {})
    assert resp["error"]["code"] == -32602


def test_unknown_method_is_method_not_found():
    resp = _h(_mcp(), {"jsonrpc": "2.0", "id": 5, "method": "frobnicate"})
    assert resp["error"]["code"] == -32601


def test_notification_gets_no_response():
    resp = _h(_mcp(), {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert resp is None


def test_ping_returns_empty_result():
    resp = _h(_mcp(), {"jsonrpc": "2.0", "id": 7, "method": "ping"})
    assert resp["result"] == {}


def test_request_with_id_zero_is_not_treated_as_a_notification():
    # id 0 is a valid request id; presence of the key, not its truthiness,
    # distinguishes a request from a notification.
    resp = _h(_mcp(), {"jsonrpc": "2.0", "id": 0, "method": "ping"})
    assert resp is not None
    assert resp["id"] == 0
    assert resp["result"] == {}


def test_request_missing_method_is_invalid_request():
    resp = _h(_mcp(), {"jsonrpc": "2.0", "id": 5})
    assert resp["error"]["code"] == -32600


def test_process_line_reports_parse_error():
    out = asyncio.run(_mcp().process_line("not json"))
    assert json.loads(out)["error"]["code"] == -32700


def test_process_line_roundtrips_a_request():
    line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    out = asyncio.run(_mcp().process_line(line))
    assert json.loads(out)["result"] == {}


def test_process_line_notification_returns_none():
    line = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert asyncio.run(_mcp().process_line(line)) is None
