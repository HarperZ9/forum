"""Forum: the always-on daemon, witnessed and durable (v0.7).

Starts the HTTP daemon on an ephemeral port over a durable file ledger, drives
it over a real socket (submit a request, read the witnessed answer, check the
status and verify the ledger), then stops. A scripted executor stands in for a
real model so this runs offline; in real use pass an ApiExecutor or a model CLI
via SubprocessExecutor.

Run:  python examples/run_daemon.py        # no install, nothing to download
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.daemon import Daemon, build_orchestrator
from forum.executor import Result


class ScriptedExecutor:
    async def run(self, assignment):
        agent = assignment.agent
        if agent == "coordinator":
            out = (
                '{"tasks": ['
                '{"id": "T1", "agent": "backend", "instruction": "design the schema", "depends_on": []},'
                '{"id": "T2", "agent": "technical-writing", "instruction": "document it", "depends_on": ["T1"]}'
                "]}"
            )
        elif agent == "validator":
            out = '{"ok": true, "score": 0.9, "reason": "looks right"}'
        elif agent == "synthesizer":
            out = "Shipped: a schema and its documentation."
        else:
            out = "handled: " + assignment.instruction
        return Result(assignment.task_id, assignment.agent, out)


async def _request(port: int, raw: bytes) -> tuple[int, bytes]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(raw)
    await writer.drain()
    data = await reader.read(-1)
    writer.close()
    await writer.wait_closed()
    head, _, body = data.partition(b"\r\n\r\n")
    status = int(head.split(b"\r\n")[0].split(b" ")[1])
    return status, body


def _post(path: str, payload: bytes) -> bytes:
    return (
        f"POST {path} HTTP/1.1\r\nHost: x\r\nContent-Length: {len(payload)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode() + payload


def _get(path: str) -> bytes:
    return f"GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n".encode()


async def main() -> None:
    workdir = tempfile.mkdtemp(prefix="forum-daemon-")
    daemon = Daemon(build_orchestrator(workdir, executor=ScriptedExecutor()), port=0)
    await daemon.start()
    print(f"daemon up on http://127.0.0.1:{daemon.port}  (ledger: {workdir})")
    try:
        _, body = await _request(daemon.port, _post("/submit", b'{"request": "build a schema and document it"}'))
        answer = json.loads(body)
        print("submit answer    :", answer["answer"])
        print("submit checkpoint:", answer["checkpoint"][:16], "...")

        _, body = await _request(daemon.port, _get("/status"))
        status = json.loads(body)
        print("status entries   :", status["entries"])

        _, body = await _request(daemon.port, _get("/verify"))
        print("verify           :", json.loads(body))
    finally:
        await daemon.stop()
        print("daemon stopped, ledger persisted at", workdir)


if __name__ == "__main__":
    asyncio.run(main())
