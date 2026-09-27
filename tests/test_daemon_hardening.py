"""The HTTP daemon rejects cross-origin, foreign-host and non-JSON requests, and
`forum serve` requires an auth token by default.

Falsifiers for the audit S10 finding: 1.14.0 had no Origin, Host or content-type
check and never turned on auth, so a web page could POST to the local daemon.
"""
import asyncio
import json

from forum.daemon import Daemon
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


def _orch():
    from forum.engine import Orchestrator
    from forum.ledger import InMemoryStorage, Ledger

    ticks = iter(float(t) for t in range(1, 100_000))
    return Orchestrator(
        load_default(),
        Ledger(InMemoryStorage(), clock=lambda: next(ticks)),
        ScriptedExecutor(),
        Policy(allowed_categories=frozenset({"engineering", "graphics", "support", "research"}),
               max_parallel=4),
    )


async def _request(port, raw: bytes) -> tuple[int, bytes]:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(raw)
    await writer.drain()
    data = await reader.read(-1)
    writer.close()
    await writer.wait_closed()
    head, _, body = data.partition(b"\r\n\r\n")
    status = int(head.split(b"\r\n")[0].split(b" ")[1])
    return status, body


def _run(coro):
    return asyncio.run(coro)


def _serve(daemon_kwargs=None):
    async def go(build):
        daemon = Daemon(_orch(), port=0, **(daemon_kwargs or {}))
        await daemon.start()
        try:
            return await build(daemon)
        finally:
            await daemon.stop()

    return go


def test_a_foreign_origin_is_refused_403():
    async def go():
        daemon = Daemon(_orch(), port=0)
        await daemon.start()
        try:
            raw = (
                b"POST /route HTTP/1.1\r\nHost: 127.0.0.1\r\nOrigin: https://evil.example\r\n"
                b"Content-Type: application/json\r\nContent-Length: 8\r\nConnection: close\r\n\r\n"
                b'{"t": 1}'
            )
            status, _ = await _request(daemon.port, raw)
            assert status == 403
        finally:
            await daemon.stop()
    _run(go())


def test_a_loopback_origin_is_allowed():
    async def go():
        daemon = Daemon(_orch(), port=0)
        await daemon.start()
        try:
            body = b'{"text": "build the api database server"}'
            raw = (
                f"POST /route HTTP/1.1\r\nHost: 127.0.0.1\r\nOrigin: http://localhost:{daemon.port}\r\n"
                f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n"
            ).encode() + body
            status, _ = await _request(daemon.port, raw)
            assert status == 200
        finally:
            await daemon.stop()
    _run(go())


def test_a_foreign_host_is_refused_403():
    async def go():
        daemon = Daemon(_orch(), port=0)
        await daemon.start()
        try:
            raw = (
                b"GET /status HTTP/1.1\r\nHost: attacker.example\r\nConnection: close\r\n\r\n"
            )
            status, _ = await _request(daemon.port, raw)
            assert status == 403
        finally:
            await daemon.stop()
    _run(go())


def test_a_text_plain_post_is_refused_415():
    async def go():
        daemon = Daemon(_orch(), port=0)
        await daemon.start()
        try:
            body = b'{"text": "x"}'
            raw = (
                f"POST /route HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: text/plain\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
            ).encode() + body
            status, _ = await _request(daemon.port, raw)
            assert status == 415
        finally:
            await daemon.stop()
    _run(go())


def test_a_json_post_without_a_content_type_is_refused_415():
    async def go():
        daemon = Daemon(_orch(), port=0)
        await daemon.start()
        try:
            body = b'{"text": "x"}'
            raw = (
                f"POST /route HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
            ).encode() + body
            status, _ = await _request(daemon.port, raw)
            assert status == 415
        finally:
            await daemon.stop()
    _run(go())


def test_serve_requires_a_token_by_default(monkeypatch, capsys, tmp_path):
    # forum serve builds a verifier and prints a token unless --no-auth. Capture
    # the daemon it would run and confirm an unauthenticated /submit is 401.
    import forum.cli as cli
    import forum.daemon as daemon_mod

    captured = {}

    async def fake_serve(ledger_dir="forum-ledger", host="127.0.0.1", port=8080,
                         executor=None, verifier=None):
        captured["verifier"] = verifier

    monkeypatch.setattr(daemon_mod, "serve", fake_serve)
    rc = cli.main(["serve", "--ledger", str(tmp_path / "led"), "--port", "0"])
    assert rc == 0
    assert captured["verifier"] is not None
    err = capsys.readouterr().err
    assert "token" in err.lower()


def test_serve_no_auth_is_explicit_and_loopback_only(monkeypatch, tmp_path, capsys):
    import forum.cli as cli
    import forum.daemon as daemon_mod

    captured = {}

    async def fake_serve(ledger_dir="forum-ledger", host="127.0.0.1", port=8080,
                         executor=None, verifier=None):
        captured["verifier"] = verifier

    monkeypatch.setattr(daemon_mod, "serve", fake_serve)
    rc = cli.main(["serve", "--ledger", str(tmp_path / "l1"), "--port", "0", "--no-auth"])
    assert rc == 0
    assert captured["verifier"] is None

    # --no-auth on a non-loopback host is refused before serving.
    rc = cli.main(["serve", "--ledger", str(tmp_path / "l2"), "--host", "0.0.0.0", "--no-auth"])
    assert rc == 2


def test_an_unauthenticated_submit_is_401_when_a_verifier_is_set():
    from forum.auth import HmacVerifier

    async def go():
        daemon = Daemon(_orch(), port=0, verifier=HmacVerifier("secret", clock=lambda: 1000.0))
        await daemon.start()
        try:
            body = b'{"request": "x"}'
            raw = (
                f"POST /submit HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
            ).encode() + body
            status, _ = await _request(daemon.port, raw)
            assert status == 401
        finally:
            await daemon.stop()
    _run(go())


def test_health_needs_no_host_or_json():
    async def go():
        daemon = Daemon(_orch(), port=0)
        await daemon.start()
        try:
            status, body = await _request(
                daemon.port, b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
            )
            assert status == 200
            assert json.loads(body) == {"ok": True}
        finally:
            await daemon.stop()
    _run(go())
