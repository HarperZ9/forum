from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from forum import __version__
from forum.engine import Orchestrator
from forum.http_surface import HttpSurface

MCP_PROTOCOL_VERSION = "2024-11-05"


def _ok(mid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _body(obj: dict) -> bytes:
    return json.dumps(obj).encode("utf-8")


def _submit_body(arguments: dict) -> bytes:
    body = {"request": arguments.get("request", "")}
    for key in (
        "context_token_budget",
        "request_context_token_budget",
        "task_context_token_budget",
        "upstream_token_budget",
    ):
        if key in arguments:
            body[key] = arguments[key]
    if "delivery_profile" in arguments:
        body["delivery_profile"] = arguments["delivery_profile"]
    return _body(body)


def _humanize_body(arguments: dict) -> bytes:
    body = {
        "text": arguments.get("text", ""),
        "audience": arguments.get("audience", "operator"),
    }
    if "profile" in arguments:
        body["profile"] = arguments["profile"]
    return _body(body)


# Tool name -> (arguments) -> (http_method, path, body). Each tool is served by
# the shared HttpSurface, so the MCP and HTTP surfaces cannot drift.
_TOOL_ROUTES = {
    "submit": lambda a: ("POST", "/submit", _submit_body(a)),
    "route": lambda a: ("POST", "/route", _body({"text": a.get("text", "")})),
    "plan": lambda a: ("POST", "/plan", _body({"request": a.get("request", "")})),
    "humanize": lambda a: ("POST", "/humanize", _humanize_body(a)),
    "status": lambda a: ("GET", "/status", b""),
    "verify": lambda a: ("GET", "/verify", b""),
    "ledger_get": lambda a: ("GET", f"/ledger/{a.get('seq')}", b""),
}

_TOOL_ALIASES = {
    "forum.submit": "submit",
    "forum.route": "route",
    "forum.plan": "plan",
    "forum.prose.humanize": "humanize",
    "forum.status": "flagship_status",
    "forum.doctor": "flagship_doctor",
    "forum.verify": "verify",
    "forum.ledger.get": "ledger_get",
    "forum.ledger.summary": "ledger_summary",
}

_CONTEXT_BUDGET_PROPERTIES = {
    "context_token_budget": {
        "type": "integer",
        "description": "run-wide approximate context token budget",
    },
    "request_context_token_budget": {
        "type": "integer",
        "description": "request-level context token budget",
    },
    "task_context_token_budget": {
        "type": "integer",
        "description": "per-task context token budget",
    },
    "upstream_token_budget": {
        "type": "integer",
        "description": "per-upstream injection token budget",
    },
}

_SUBMIT_PROPERTIES = {
    "request": {"type": "string", "description": "the request to fulfil"},
    "delivery_profile": {
        "type": "string",
        "description": "delivery profile: operator, engineer, researcher, executive",
    },
    **_CONTEXT_BUDGET_PROPERTIES,
}

_TOOL_SPECS = [
    {
        "name": "submit",
        "description": "Plan a plain request, run it, and return a witnessed answer with the ledger checkpoint.",
        "inputSchema": {
            "type": "object",
            "properties": _SUBMIT_PROPERTIES,
            "required": ["request"],
        },
    },
    {
        "name": "route",
        "description": "Score a request against the roster and return the decided lane (or escalation).",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "the request text to route"}},
            "required": ["text"],
        },
    },
    {
        "name": "plan",
        "description": "Turn a plain request into a task plan without running it.",
        "inputSchema": {
            "type": "object",
            "properties": {"request": {"type": "string", "description": "the request to plan"}},
            "required": ["request"],
        },
    },
    {
        "name": "status",
        "description": "Return the ledger entry count and current checkpoint.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "verify",
        "description": "Verify the ledger chain and payload bodies.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ledger_get",
        "description": "Fetch one ledger entry by its sequence number.",
        "inputSchema": {
            "type": "object",
            "properties": {"seq": {"type": "integer", "description": "the entry sequence number"}},
            "required": ["seq"],
        },
    },
    {
        "name": "forum.submit",
        "description": "Plan a plain request, run it, and return a witnessed answer with the ledger checkpoint.",
        "inputSchema": {
            "type": "object",
            "properties": _SUBMIT_PROPERTIES,
            "required": ["request"],
        },
    },
    {
        "name": "forum.route",
        "description": "Score a request against the roster and return the decided lane or escalation.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "the request text to route"}},
            "required": ["text"],
        },
    },

    {
        "name": "forum.prose.humanize",
        "description": "Turn stiff model or agent prose into clearer operator-facing wording without adding facts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "agent or model prose to clarify"},
                "audience": {"type": "string", "description": "target reader label; defaults to operator"},
                "profile": {
                    "type": "string",
                    "description": "delivery profile: operator, engineer, researcher, executive",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "forum.status",
        "description": "Return Forum's Project Telos operator-spine status as a flagship action envelope.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "forum.doctor",
        "description": "Check Forum's Project Telos operator-spine readiness as a flagship action envelope.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "forum.ledger.summary",
        "description": "Summarize the witnessed causal ledger into counts, verification, and payload weight.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class McpSurface:
    """An MCP (JSON-RPC 2.0) adapter over the same HttpSurface logic.

    The lone optional edge. Each tool maps to an HTTP method and path and is
    served by the shared HttpSurface, so the MCP and HTTP surfaces never drift.
    No stdio lives in handle(); serve_stdio() wires real streams around it, and
    process_line() is the testable seam between a raw line and a response line.
    """

    def __init__(self, orchestrator: Orchestrator) -> None:
        self._orchestrator = orchestrator
        self._surface = HttpSurface(orchestrator)

    async def handle(self, message: dict) -> dict | None:
        mid = message.get("id")
        if "id" not in message:
            return None  # a JSON-RPC notification: nothing to run, no response
        method = message.get("method")
        if method is None:
            return _err(mid, -32600, "invalid request: method is required")
        if method == "initialize":
            return _ok(mid, {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "forum", "version": __version__},
            })
        if method == "tools/list":
            return _ok(mid, {"tools": _TOOL_SPECS})
        if method == "tools/call":
            return await self._call_tool(mid, message.get("params") or {})
        if method == "ping":
            return _ok(mid, {})
        return _err(mid, -32601, f"method not found: {method}")

    async def _call_tool(self, mid: Any, params: dict) -> dict:
        name = params.get("name")
        canonical = _TOOL_ALIASES.get(name, name) if isinstance(name, str) else None
        if canonical in {"flagship_status", "flagship_doctor"}:
            from forum.flagship import doctor_payload, status_payload

            payload = status_payload() if canonical == "flagship_status" else doctor_payload()
            return _ok(mid, {
                "content": [{"type": "text", "text": json.dumps(payload)}],
                "isError": False,
            })
        if canonical == "ledger_summary":
            from forum.report import summarize

            return _ok(mid, {
                "content": [{"type": "text", "text": json.dumps(summarize(self._orchestrator.ledger))}],
                "isError": False,
            })
        route = _TOOL_ROUTES.get(canonical) if isinstance(canonical, str) else None
        if route is None:
            return _err(mid, -32602, f"unknown tool: {name!r}")
        http_method, path, body = route(params.get("arguments") or {})
        response = await self._surface.dispatch(http_method, path, body)
        return _ok(mid, {
            "content": [{"type": "text", "text": response.body.decode("utf-8")}],
            "isError": response.status >= 400,
        })

    async def process_line(self, line: str) -> str | None:
        """Parse one JSON-RPC line, handle it, and serialize the response.

        Returns None for a blank line or a notification (nothing to send back).
        """
        line = line.strip()
        if not line:
            return None
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return json.dumps(_err(None, -32700, "parse error"))
        response = await self.handle(message)
        return None if response is None else json.dumps(response)


async def serve_stdio(orchestrator: Orchestrator | None = None, ledger_dir: str = "forum-ledger") -> None:
    """Serve MCP over stdio: one JSON-RPC message per line, in and out.

    Builds a durable-ledger Orchestrator by default. Reads stdin in a thread so
    the event loop is not blocked and the transport stays cross-platform.
    """
    if orchestrator is None:
        from forum.daemon import build_orchestrator

        orchestrator = build_orchestrator(ledger_dir)
    surface = McpSurface(orchestrator)
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break  # EOF
        out = await surface.process_line(line)
        if out is not None:
            sys.stdout.write(out + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(serve_stdio())
