import asyncio
import json

from forum.auth import SCOPE_READ, required_scope
from forum.cli import main
from forum.engine import Orchestrator
from forum.executor import EchoExecutor
from forum.flagship import status_payload
from forum.http_surface import HttpSurface
from forum.ledger import InMemoryStorage, Ledger
from forum.mcp_surface import TOOL_ANNOTATIONS, McpSurface
from forum.policy import Policy
from forum.roster import load_default

TEXT = "Prior to launch, utilize the report in order to assist users."
CLEAN = "Before launch, use the report to help users."
ALL = frozenset({"engineering", "graphics", "support", "research"})


def _orch():
    ticks = iter(float(t) for t in range(1, 100_000))
    return Orchestrator(load_default(), Ledger(InMemoryStorage(), clock=lambda: next(ticks)),
                        EchoExecutor(), Policy(allowed_categories=ALL, max_parallel=4))


def _post(path, body):
    resp = asyncio.run(HttpSurface(_orch()).dispatch("POST", path, json.dumps(body).encode()))
    return resp.status, json.loads(resp.body)


def _mcp(method, params=None):
    msg = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return asyncio.run(McpSurface(_orch()).handle(msg))


def _tool(name, arguments):
    resp = _mcp("tools/call", {"name": name, "arguments": arguments})
    return json.loads(resp["result"]["content"][0]["text"])


def test_cli_clarify_outputs_json(capsys):
    assert main(["clarify", TEXT]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "forum.prose-clarification/v1"
    assert payload["engine"] == "forum-builtin"
    assert payload["output"] == CLEAN
    assert "deprecation" not in payload


def test_cli_clarify_accepts_engine_and_profile(capsys):
    assert main(["clarify", TEXT, "--engine", "forum-builtin", "--profile", "engineer"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["engine"] == "forum-builtin"
    assert payload["profile"] == "engineer"


def test_cli_clarify_rejects_unknown_engine(capsys):
    assert main(["clarify", TEXT, "--engine", "gpt"]) == 2
    assert "unknown clarify engine" in capsys.readouterr().err


def test_cli_humanize_alias_returns_same_result_with_notice(capsys):
    assert main(["humanize", TEXT]) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["output"] == CLEAN
    assert payload["schema"] == "forum.prose-humanization/v1"
    assert payload["deprecation"]["replacement"] == "clarify"
    assert "deprecated" in captured.err


def test_http_clarify_route():
    status, body = _post("/clarify", {"text": TEXT})
    assert status == 200
    assert body["schema"] == "forum.prose-clarification/v1"
    assert body["output"] == CLEAN


def test_http_clarify_rejects_bad_engine():
    status, body = _post("/clarify", {"text": TEXT, "engine": "gpt"})
    assert status == 400
    assert "unknown clarify engine" in body["error"]


def test_http_humanize_alias_matches_clarify():
    _, new = _post("/clarify", {"text": TEXT})
    status, old = _post("/humanize", {"text": TEXT})
    assert status == 200
    assert old["output"] == new["output"] and old["edits"] == new["edits"]
    assert old["schema"] == "forum.prose-humanization/v1"
    assert old["deprecation"]["deprecated"] is True


def test_clarify_route_needs_read_scope_like_humanize():
    assert required_scope("POST", "/clarify") == SCOPE_READ
    assert required_scope("POST", "/humanize") == SCOPE_READ


def test_mcp_lists_clarify_with_annotations_and_marks_alias_deprecated():
    tools = {t["name"]: t for t in _mcp("tools/list")["result"]["tools"]}
    clarify = tools["forum.prose.clarify"]
    assert clarify["annotations"]["readOnlyHint"] is True
    assert clarify["annotations"]["openWorldHint"] is False
    assert clarify["annotations"]["idempotentHint"] is True
    assert "engine" in clarify["inputSchema"]["properties"]
    alias = tools["forum.prose.humanize"]
    assert alias["description"].startswith("Deprecated")
    assert alias["annotations"] == {**clarify["annotations"], "title": alias["title"]}
    assert TOOL_ANNOTATIONS["forum.prose.clarify"]["readOnlyHint"] is True


def test_mcp_clarify_and_alias_return_same_output():
    new = _tool("forum.prose.clarify", {"text": TEXT, "profile": "engineer"})
    old = _tool("forum.prose.humanize", {"text": TEXT, "profile": "engineer"})
    assert new["schema"] == "forum.prose-clarification/v1"
    assert new["output"] == old["output"] == CLEAN
    assert old["deprecation"]["replacement"] == "clarify"


def test_flagship_status_lists_clarify():
    tools = status_payload()["native"]["mcp_tools"]
    assert "forum.prose.clarify" in tools
