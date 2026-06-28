from __future__ import annotations

import dataclasses
import json
from typing import Any

from forum.engine import Orchestrator
from forum.receipts import submit_receipt

MAX_BODY = 1 << 20  # 1 MiB cap on a request body

_REASONS = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    408: "Request Timeout",
    413: "Payload Too Large",
    500: "Internal Server Error",
    502: "Bad Gateway",
}

_KNOWN_PATHS = {"/health", "/status", "/verify", "/checkpoint", "/route", "/plan", "/submit", "/humanize"}


@dataclasses.dataclass(frozen=True, slots=True)
class Response:
    status: int
    body: bytes
    content_type: str = "application/json"

    @property
    def reason(self) -> str:
        return _REASONS.get(self.status, "Unknown")


def json_response(obj: Any, status: int = 200) -> Response:
    return Response(status, json.dumps(obj).encode("utf-8"))


def error(status: int, message: str) -> Response:
    return json_response({"error": message}, status)


class HttpSurface:
    """Maps an HTTP method and path to the Orchestrator and serializes JSON.

    No sockets live here; `dispatch` is a plain coroutine so every endpoint is
    testable without a network. The transport (forum.daemon) feeds it a parsed
    (method, path, body) and writes the Response back.
    """

    def __init__(self, orchestrator: Orchestrator) -> None:
        self._orch = orchestrator

    async def dispatch(self, method: str, path: str, body: bytes) -> Response:
        try:
            return await self._route(method, path, body)
        except Exception as exc:  # never swallow: report with context
            return error(500, f"{type(exc).__name__}: {exc}")

    async def _route(self, method: str, path: str, body: bytes) -> Response:
        if method == "GET" and path == "/health":
            return json_response({"ok": True})
        if method == "GET" and path == "/status":
            led = self._orch.ledger
            return json_response({"entries": led.count(), "checkpoint": led.checkpoint()})
        if method == "GET" and path == "/verify":
            led = self._orch.ledger
            return json_response({"chain": led.verify(), "deep": led.verify(deep=True)})
        if method == "GET" and path == "/checkpoint":
            return json_response({"checkpoint": self._orch.ledger.checkpoint()})
        if method == "GET" and path.startswith("/ledger/"):
            return self._ledger_get(path)
        if method == "GET" and path.startswith("/replay/"):
            return self._replay(path)
        if method == "POST" and path == "/route":
            return self._route_text(body)
        if method == "POST" and path == "/plan":
            return await self._plan(body)
        if method == "POST" and path == "/submit":
            return await self._submit(body)
        if method == "POST" and path == "/humanize":
            return self._humanize(body)

        if path in _KNOWN_PATHS or path.startswith("/ledger/") or path.startswith("/replay/"):
            return error(405, f"method {method} not allowed for {path}")
        return error(404, f"no route for {path}")

    # --- helpers ---

    def _read_json(self, body: bytes):
        if not body:
            return None, error(400, "expected a JSON body")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return None, error(400, "body is not valid JSON")
        if not isinstance(data, dict):
            return None, error(400, "body must be a JSON object")
        return data, None

    def _str_field(self, data: dict, name: str):
        value = data.get(name)
        if not isinstance(value, str) or not value:
            return None, error(400, f"field {name!r} (a non-empty string) is required")
        return value, None

    def _seq_suffix(self, path: str, prefix: str):
        try:
            return int(path[len(prefix):]), None
        except ValueError:
            return None, error(400, f"{prefix}<seq> requires an integer seq")

    # --- handlers ---

    def _ledger_get(self, path: str) -> Response:
        seq, err = self._seq_suffix(path, "/ledger/")
        if err:
            return err
        try:
            entry = self._orch.ledger.get(seq)
        except KeyError:
            return error(404, f"no ledger entry at seq {seq}")
        return json_response(dataclasses.asdict(entry))

    def _replay(self, path: str) -> Response:
        seq, err = self._seq_suffix(path, "/replay/")
        if err:
            return err
        entries = self._orch.ledger.replay(until=seq)
        return json_response({"entries": [dataclasses.asdict(e) for e in entries]})

    def _route_text(self, body: bytes) -> Response:
        data, err = self._read_json(body)
        if err:
            return err
        text, err = self._str_field(data, "text")
        if err:
            return err
        result = self._orch.route(text)
        return json_response({
            "decided": result.decided,
            "confidence": result.confidence,
            "needs_escalation": result.needs_escalation,
            "candidates": [{"agent": c.agent, "score": c.score} for c in result.candidates],
        })


    def _humanize(self, body: bytes) -> Response:
        from forum.humanize import humanize_text

        data, err = self._read_json(body)
        if err:
            return err
        text, err = self._str_field(data, "text")
        if err:
            return err
        audience = data.get("audience", "operator")
        if not isinstance(audience, str) or not audience:
            return error(400, "field 'audience' must be a non-empty string when provided")
        try:
            return json_response(humanize_text(text, audience=audience))
        except ValueError as exc:
            return error(400, str(exc))

    async def _plan(self, body: bytes) -> Response:
        data, err = self._read_json(body)
        if err:
            return err
        request, err = self._str_field(data, "request")
        if err:
            return err
        try:
            plan = await self._orch.coordinator.plan(
                request, self._orch.roster, self._orch.executor
            )
        except ValueError as exc:
            return error(502, f"the executor did not return a valid plan ({exc})")
        return json_response({"tasks": [
            {"id": t.id, "agent": t.agent, "instruction": t.instruction,
             "depends_on": list(t.depends_on)}
            for t in plan.tasks
        ]})

    async def _submit(self, body: bytes) -> Response:
        data, err = self._read_json(body)
        if err:
            return err
        request, err = self._str_field(data, "request")
        if err:
            return err
        before_seq = self._orch.ledger.count()
        try:
            answer = await self._orch.submit(request)
        except ValueError as exc:
            return error(
                502,
                "the configured executor did not return valid JSON; point the "
                f"daemon at a real model executor ({exc})",
            )
        receipt = submit_receipt(
            self._orch.ledger,
            before_seq=before_seq,
            request=request,
            answer=answer,
            executor=self._orch.executor,
        )
        return json_response({
            "answer": answer,
            "checkpoint": self._orch.ledger.checkpoint(),
            "receipt": receipt,
        })
