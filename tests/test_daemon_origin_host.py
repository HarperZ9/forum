"""The daemon accepts only its own origin, and a token-holding client under any host name.

Falsifiers for review finding F10, over a real loopback socket. The first 1.15.0
candidate accepted an Origin from any loopback port, so a page served by another
local program (a dev server on localhost:5173) could drive an open daemon; it
refused every non-loopback Host even with a valid token, so a daemon bound to the
network answered no one; and it compared host names with case, so LOCALHOST failed.
"""
import asyncio
import json

from forum.auth import HmacVerifier, issue_hs256
from forum.daemon import Daemon, build_orchestrator

SECRET = "s" * 32
ROUTE = json.dumps({"text": "build a login api"}).encode()


def _raw(method, path, headers, body=b""):
    lines = [f"{method} {path} HTTP/1.1", *(f"{k}: {v}" for k, v in headers.items()),
             f"Content-Length: {len(body)}", "Connection: close"]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body


async def _send(port, raw):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(raw)
    await writer.drain()
    data = await reader.read(-1)
    writer.close()
    await writer.wait_closed()
    return int(data.split(b"\r\n", 1)[0].split(b" ")[1])


def _status(tmp_path, raw_for_port, **daemon_kwargs):
    async def go():
        daemon = Daemon(build_orchestrator(str(tmp_path / "ledger")), port=0, **daemon_kwargs)
        await daemon.start()
        try:
            return await _send(daemon.port, raw_for_port(daemon.port))
        finally:
            await daemon.stop()
    return asyncio.run(go())


def _token():
    return issue_hs256(subject="op", roles=["operator"], secret=SECRET, ttl_seconds=None)


def test_an_origin_on_another_loopback_port_is_refused(tmp_path):
    status = _status(tmp_path, lambda port: _raw("POST", "/route", {
        "Host": f"127.0.0.1:{port}", "Origin": "http://localhost:5173",
        "Content-Type": "application/json"}, ROUTE))
    assert status == 403


def test_an_origin_without_a_port_is_refused_unless_the_daemon_is_on_port_80(tmp_path):
    status = _status(tmp_path, lambda port: _raw("POST", "/route", {
        "Host": f"127.0.0.1:{port}", "Origin": "http://localhost",
        "Content-Type": "application/json"}, ROUTE))
    assert status == 403


def test_the_daemons_own_origin_is_allowed_in_any_case(tmp_path):
    status = _status(tmp_path, lambda port: _raw("POST", "/route", {
        "Host": f"127.0.0.1:{port}", "Origin": f"http://LocalHost:{port}",
        "Content-Type": "application/json"}, ROUTE))
    assert status == 200


def test_an_authenticated_daemon_answers_its_lan_name(tmp_path):
    status = _status(tmp_path, lambda port: _raw("GET", "/status", {
        "Host": f"forum.lan:{port}", "Authorization": f"Bearer {_token()}"}),
        verifier=HmacVerifier(SECRET))
    assert status == 200


def test_an_authenticated_daemon_still_needs_the_token_under_a_foreign_host(tmp_path):
    status = _status(tmp_path, lambda port: _raw("GET", "/status", {"Host": f"rebind.example:{port}"}),
                     verifier=HmacVerifier(SECRET))
    assert status == 401


def test_an_authenticated_daemon_still_refuses_a_foreign_origin(tmp_path):
    status = _status(tmp_path, lambda port: _raw("POST", "/route", {
        "Host": f"forum.lan:{port}", "Origin": "https://evil.example",
        "Content-Type": "application/json", "Authorization": f"Bearer {_token()}"}, ROUTE),
        verifier=HmacVerifier(SECRET))
    assert status == 403


def test_host_names_compare_without_case(tmp_path):
    status = _status(tmp_path, lambda port: _raw("GET", "/status", {"Host": f"LOCALHOST:{port}"}))
    assert status == 200


def test_an_open_daemon_still_refuses_a_foreign_host(tmp_path):
    status = _status(tmp_path, lambda port: _raw("GET", "/status", {"Host": f"rebind.example:{port}"}))
    assert status == 403
