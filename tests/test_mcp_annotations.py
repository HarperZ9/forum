"""Every MCP tool states its title and read/write hints.

The Anthropic Software Directory Policy requires readOnlyHint, destructiveHint
and title on every tool a listed server exposes.
"""
import asyncio

from forum.daemon import build_orchestrator
from forum.mcp_surface import TOOL_ANNOTATIONS, McpSurface

HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def _listed(surface):
    resp = asyncio.run(surface.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}))
    return resp["result"]["tools"]


def test_every_listed_tool_is_annotated(tmp_path):
    orch = build_orchestrator(str(tmp_path / "ledger"))
    tools = _listed(McpSurface(orch, allow_gate_decisions=True))
    assert {tool["name"] for tool in tools} == set(TOOL_ANNOTATIONS)
    for tool in tools:
        notes = tool["annotations"]
        assert notes["title"] and tool["title"] == notes["title"], tool["name"]
        assert all(isinstance(notes[key], bool) for key in HINTS), tool["name"]
        assert len(tool["name"]) <= 64
        if notes["readOnlyHint"]:
            assert notes["destructiveHint"] is False, tool["name"]


def test_hints_match_tool_effects(tmp_path):
    tools = _listed(McpSurface(build_orchestrator(str(tmp_path / "ledger")),
                               allow_gate_decisions=True))
    by_name = {tool["name"]: tool["annotations"] for tool in tools}
    for name in ("forum.route", "forum.context.preflight", "forum.runtime.inspect", "gate_list"):
        assert by_name[name]["readOnlyHint"] is True, name
    assert by_name["forum.submit"]["readOnlyHint"] is False
    assert by_name["forum.submit"]["openWorldHint"] is True
    assert by_name["gate_reject"]["destructiveHint"] is True
