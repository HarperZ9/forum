"""Forum preflight-only MCP entrypoint. No model executor or disk ledger."""
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))
from forum.engine import Orchestrator
from forum.ledger import Ledger, InMemoryStorage
from forum.mcp_surface import McpSurface
from forum.policy import Policy
from forum.roster import load_default

ALLOWED = frozenset({'forum.route', 'forum.context.preflight',
                     'forum.runtime.inspect', 'forum.prose.contract',
                     'forum.status', 'forum.doctor'})


class PreflightSurface(McpSurface):
    def __init__(self):
        orch = Orchestrator(load_default(), Ledger(InMemoryStorage()), None,
                            Policy(frozenset({'engineering', 'graphics', 'support', 'research'})))
        super().__init__(orch)
        self._tools = [tool for tool in self._tools if tool['name'] in ALLOWED]

    async def _call_tool(self, mid, params):
        if params.get('name') not in ALLOWED:
            return {'jsonrpc': '2.0', 'id': mid, 'result': {'isError': True,
                    'content': [{'type': 'text', 'text': 'PREFLIGHT_ONLY: execution and grants are unavailable'}]}}
        return await super()._call_tool(mid, params)


async def serve():
    surface = PreflightSurface()
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError('request must be an object')
            reply = await surface.handle(message)
        except (ValueError, TypeError, AttributeError):
            reply = {'jsonrpc': '2.0', 'id': None,
                     'error': {'code': -32600, 'message': 'invalid request'}}
        if reply is not None:
            print(json.dumps(reply), flush=True)


if __name__ == '__main__':
    if len(sys.argv) != 1:
        raise SystemExit('this preflight package takes no launch arguments')
    asyncio.run(serve())
