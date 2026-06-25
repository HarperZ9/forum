import asyncio
import json

from forum.daemon import Daemon, build_orchestrator
from forum.executor import Result
from forum.policy import Policy
from forum.roster import load_default


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


async def _request(port, raw: bytes) -> tuple[int, bytes]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(raw)
    await writer.drain()
    data = await reader.read(-1)  # server sends Connection: close
    writer.close()
    await writer.wait_closed()
    head, _, body = data.partition(b"\r\n\r\n")
    status = int(head.split(b"\r\n")[0].split(b" ")[1])
    return status, body


def _get(path):
    return f"GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n".encode()


def _post(path, payload: bytes):
    return (
        f"POST {path} HTTP/1.1\r\nHost: x\r\nContent-Length: {len(payload)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode() + payload


def test_socket_round_trip_health():
    async def go():
        orch = build_orchestrator_in_memory()
        daemon = Daemon(orch, port=0)
        await daemon.start()
        try:
            status, body = await _request(daemon.port, _get("/health"))
            assert status == 200
            assert json.loads(body) == {"ok": True}
        finally:
            await daemon.stop()
    asyncio.run(go())


def test_socket_post_route():
    async def go():
        daemon = Daemon(build_orchestrator_in_memory(), port=0)
        await daemon.start()
        try:
            status, body = await _request(
                daemon.port, _post("/route", b'{"text": "build the api database server"}')
            )
            assert status == 200
            assert json.loads(body)["decided"] == "backend"
        finally:
            await daemon.stop()
    asyncio.run(go())


def test_oversize_body_is_413():
    async def go():
        daemon = Daemon(build_orchestrator_in_memory(), port=0)
        await daemon.start()
        try:
            # advertise a huge Content-Length; the parser rejects before reading
            raw = (
                b"POST /submit HTTP/1.1\r\nHost: x\r\nContent-Length: 2000000\r\n"
                b"Connection: close\r\n\r\n"
            )
            status, _ = await _request(daemon.port, raw)
            assert status == 413
        finally:
            await daemon.stop()
    asyncio.run(go())


def test_stop_then_connect_fails():
    async def go():
        daemon = Daemon(build_orchestrator_in_memory(), port=0)
        await daemon.start()
        port = daemon.port
        await daemon.stop()
        try:
            await asyncio.open_connection("127.0.0.1", port)
            assert False, "connection should have been refused after stop"
        except OSError:
            pass
    asyncio.run(go())


def test_durable_ledger_survives_a_daemon_restart(tmp_path):
    async def first():
        daemon = Daemon(build_orchestrator(str(tmp_path), executor=ScriptedExecutor()), port=0)
        await daemon.start()
        try:
            status, _ = await _request(daemon.port, _post("/submit", b'{"request": "design an api"}'))
            assert status == 200
        finally:
            await daemon.stop()

    async def second():
        daemon = Daemon(build_orchestrator(str(tmp_path), executor=ScriptedExecutor()), port=0)
        await daemon.start()
        try:
            status, body = await _request(daemon.port, _get("/status"))
            data = json.loads(body)
            assert status == 200
            assert data["entries"] > 0          # the prior run persisted
            assert data["verified"] is True
        finally:
            await daemon.stop()

    asyncio.run(first())
    asyncio.run(second())


def build_orchestrator_in_memory():
    # A small helper: a non-durable orchestrator for the transport tests that
    # do not exercise persistence. Uses the durable factory against a throwaway
    # in-memory ledger via build_orchestrator with a temp dir is overkill here,
    # so build directly.
    from forum.engine import Orchestrator
    from forum.ledger import InMemoryStorage, Ledger
    ticks = iter(float(t) for t in range(1, 100_000))
    return Orchestrator(
        load_default(),
        Ledger(InMemoryStorage(), clock=lambda: next(ticks)),
        ScriptedExecutor(),
        Policy(allowed_categories=frozenset({"engineering", "graphics", "support", "research"}), max_parallel=4),
    )
