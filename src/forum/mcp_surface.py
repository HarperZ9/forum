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


# Tool name -> (arguments) -> (http_method, path, body). Each tool is served by
# the shared HttpSurface, so the MCP and HTTP surfaces cannot drift.
_TOOL_ROUTES = {
    "submit": lambda a: ("POST", "/submit", _body({"request": a.get("request", "")})),
    "route": lambda a: ("POST", "/route", _body({"text": a.get("text", "")})),
    "plan": lambda a: ("POST", "/plan", _body({"request": a.get("request", "")})),
    "status": lambda a: ("GET", "/status", b""),
    "verify": lambda a: ("GET", "/verify", b""),
    "ledger_get": lambda a: ("GET", f"/ledger/{a.get('seq')}", b""),
}

_TOOL_SPECS = [
    {
        "name": "submit",
        "description": "Plan a plain request, run it, and return a witnessed answer with the ledger checkpoint.",
        "inputSchema": {
            "type": "object",
            "properties": {"request": {"type": "string", "description": "the request to fulfil"}},
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
]


class McpSurface:
    """An MCP (JSON-RPC 2.0) adapter over the same HttpSurface logic.

    The lone optional edge. Each tool maps to an HTTP method and path and is
    served by the shared HttpSurface, so the MCP and HTTP surfaces never drift.
    No stdio lives in handle(); serve_stdio() wires real streams around it, and
    process_line() is the testable seam between a raw line and a response line.
    """

    def __init__(self, orchestrator: Orchestrator) -> None:
        self._surface = HttpSurface(orchestrator)

    async def handle(self, message: dict) -> dict | None:
        method = message.get("method")
        mid = message.get("id")
        if method is None:
            return None
        if "id" not in message:
            return None  # a JSON-RPC notification: nothing to run, no response
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
        route = _TOOL_ROUTES.get(name)
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
