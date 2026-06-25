from __future__ import annotations

import asyncio

from forum.engine import Orchestrator
from forum.executor import EchoExecutor, Executor
from forum.http_surface import MAX_BODY, HttpSurface, Response, error
from forum.ledger import Ledger
from forum.policy import Policy
from forum.roster import Roster, load_default
from forum.storage import FileStorage

_ALL_CATEGORIES = frozenset({"engineering", "graphics", "support", "research"})


class _BodyTooLarge(Exception):
    pass


async def _read_request(reader: asyncio.StreamReader) -> tuple[str, str, bytes]:
    """Parse one HTTP/1.1 request into (method, path, body).

    Raises _BodyTooLarge if the advertised Content-Length exceeds MAX_BODY, and
    ValueError / asyncio read errors on a malformed or truncated request.
    """
    head = await reader.readuntil(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    parts = lines[0].decode("latin-1").split(" ")
    if len(parts) != 3:
        raise ValueError("malformed request line")
    method, path, _version = parts
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if not line:
            continue
        key, _, value = line.partition(b":")
        headers[key.decode("latin-1").strip().lower()] = value.decode("latin-1").strip()
    body = b""
    raw_len = headers.get("content-length")
    if raw_len is not None:
        n = int(raw_len)
        if n > MAX_BODY:
            raise _BodyTooLarge()
        body = await reader.readexactly(n)
    return method, path, body


async def _write_response(writer: asyncio.StreamWriter, response: Response) -> None:
    head = (
        f"HTTP/1.1 {response.status} {response.reason}\r\n"
        f"Content-Type: {response.content_type}\r\n"
        f"Content-Length: {len(response.body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("latin-1")
    writer.write(head + response.body)
    await writer.drain()


class Daemon:
    """An always-on HTTP/1.1 service over the Orchestrator, on stdlib asyncio.

    One Daemon owns one Orchestrator (and therefore one long-lived ledger), so
    every request witnesses into the same record. Connections are one-shot
    (Connection: close); the surface is HttpSurface.
    """

    def __init__(self, orchestrator: Orchestrator, host: str = "127.0.0.1", port: int = 8080) -> None:
        self.orchestrator = orchestrator
        self._surface = HttpSurface(orchestrator)
        self._host = host
        self._port = port
        self._server: asyncio.AbstractServer | None = None
        self._inflight: set[asyncio.Task] = set()

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        if self._server is not None and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self._port

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._inflight.add(task)
        try:
            try:
                method, path, body = await _read_request(reader)
            except _BodyTooLarge:
                await _write_response(writer, error(413, "request body too large"))
                return
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError):
                await _write_response(writer, error(400, "malformed HTTP request"))
                return
            response = await self._surface.dispatch(method, path, body)
            await _write_response(writer, response)
        finally:
            if task is not None:
                self._inflight.discard(task)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self) -> "Daemon":
        self._server = await asyncio.start_server(self._handle, self._host, self._port)
        return self

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        async with self._server:
            await self._server.serve_forever()

    async def stop(self, drain_timeout: float = 5.0) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._inflight:
            await asyncio.wait(self._inflight, timeout=drain_timeout)


def build_orchestrator(
    ledger_dir: str,
    *,
    executor: Executor | None = None,
    roster: Roster | None = None,
    policy: Policy | None = None,
) -> Orchestrator:
    """Build an Orchestrator backed by a durable file ledger and the default roster.

    The default executor is EchoExecutor, which keeps /route and the ledger
    endpoints working out of the box; /plan and /submit need a model executor
    (an ApiExecutor or a model CLI via SubprocessExecutor) and return 502 under
    EchoExecutor.
    """
    ledger = Ledger(FileStorage(ledger_dir))
    return Orchestrator(
        roster or load_default(),
        ledger,
        executor or EchoExecutor(),
        policy or Policy(allowed_categories=_ALL_CATEGORIES, max_parallel=6),
    )


async def serve(
    ledger_dir: str = "forum-ledger",
    host: str = "127.0.0.1",
    port: int = 8080,
    executor: Executor | None = None,
) -> None:
    daemon = Daemon(build_orchestrator(ledger_dir, executor=executor), host, port)
    await daemon.start()
    print(f"forum daemon on http://{daemon.host}:{daemon.port} (ledger: {ledger_dir})")
    await daemon.serve_forever()


if __name__ == "__main__":
    asyncio.run(serve())
