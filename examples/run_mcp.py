"""Forum: the MCP surface, driven offline (v0.8).

Feeds a few JSON-RPC messages through the MCP surface (initialize, tools/list,
a route call, a submit call) and prints the responses. A scripted executor
stands in for a real model so this runs offline. In real use,
`python -m forum.mcp_surface` speaks JSON-RPC over stdio to an MCP client.

Run:  python examples/run_mcp.py        # no install, nothing to download
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.engine import Orchestrator
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.mcp_surface import McpSurface
from forum.policy import Policy
from forum.roster import load_default


class ScriptedExecutor:
    async def run(self, assignment):
        agent = assignment.agent
        if agent == "coordinator":
            out = '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "design the api", "depends_on": []}]}'
        elif agent == "validator":
            out = '{"ok": true, "score": 0.9, "reason": "ok"}'
        elif agent == "synthesizer":
            out = "Shipped: the api is designed."
        else:
            out = "handled"
        return Result(assignment.task_id, assignment.agent, out)


async def main() -> None:
    ticks = iter(float(t) for t in range(1, 100_000))
    orch = Orchestrator(
        load_default(),
        Ledger(InMemoryStorage(), clock=lambda: next(ticks)),
        ScriptedExecutor(),
        Policy(allowed_categories=frozenset({"engineering", "graphics", "support", "research"}), max_parallel=4),
    )
    mcp = McpSurface(orch)
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "route", "arguments": {"text": "build the api database server"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "submit", "arguments": {"request": "design an api"}}},
    ]
    for msg in messages:
        out = await mcp.process_line(json.dumps(msg))
        print(f"-> {msg['method']}")
        print(f"   {out}")


if __name__ == "__main__":
    asyncio.run(main())
