from __future__ import annotations

from forum.auth import (
    DEFAULT_ROLE_POLICY,
    SCOPE_GATE,
    SCOPE_PLAN,
    SCOPE_ROUTE,
    SCOPE_SUBMIT,
    InvalidToken,
    RolePolicy,
    TokenVerifier,
    authorize,
    bearer_token,
    required_scope,
    witness_authz,
)
from forum.engine import Orchestrator
from forum.http_actions import HttpActionMixin
from forum.http_handlers import HttpReadMixin

# Re-exported so existing imports (forum.daemon, tests) keep resolving these off
# forum.http_surface after the wire primitives moved to forum.http_response.
from forum.http_response import MAX_BODY, Response, error, json_response
from forum.metrics import MetricsRegistry
from forum.tracing import KIND_SERVER, STATUS_ERROR, Tracer, parse_traceparent

__all__ = ["MAX_BODY", "HttpSurface", "Response", "error", "json_response"]

# The mutating verbs whose grants are worth witnessing in the audit ledger.
_MUTATING_SCOPES = frozenset({SCOPE_ROUTE, SCOPE_PLAN, SCOPE_SUBMIT, SCOPE_GATE})

_KNOWN_PATHS = {
    "/health",
    "/status",
    "/verify",
    "/checkpoint",
    "/capsule",
    "/room",
    "/runtime",
    "/context/preflight",
    "/route",
    "/plan",
    "/submit",
    "/humanize",
    "/prose/contract",
    "/gates",
    "/gate/approve",
    "/gate/edit",
    "/gate/reject",
}


def _route_template(path: str) -> str:
    """Collapse a variable-seq path to a low-cardinality span name.

    OTel names a server span by its route, not its raw target, so ``/ledger/42``
    and ``/ledger/43`` share one span name (``/ledger/{seq}``) and stay groupable
    in a backend. The raw path is kept separately as the ``url.path`` attribute.
    """
    if path.startswith("/ledger/"):
        return "/ledger/{seq}"
    if path.startswith("/replay/"):
        return "/replay/{seq}"
    return path


class HttpSurface(HttpReadMixin, HttpActionMixin):
    """Maps an HTTP method and path to the Orchestrator and serializes JSON.

    No sockets live here; `dispatch` is a plain coroutine so every endpoint is
    testable without a network. The transport (forum.daemon) feeds it a parsed
    (method, path, body) and writes the Response back. The endpoint handlers live
    on HttpReadMixin (reads + validation) and HttpActionMixin (mutations); this
    class owns dispatch, authorization, and the observability wrapping.
    """

    def __init__(
        self,
        orchestrator: Orchestrator,
        *,
        verifier: TokenVerifier | None = None,
        role_policy: RolePolicy = DEFAULT_ROLE_POLICY,
        tracer: Tracer | None = None,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self._orch = orchestrator
        # No verifier means authentication is OFF: dispatch serves every request,
        # exactly as before. Configure a verifier to require a bearer JWT and the
        # per-endpoint scope.
        self._verifier = verifier
        self._role_policy = role_policy
        # No tracer means tracing is OFF: dispatch takes the untraced fast path.
        # Configure a Tracer with an exporter to emit an OTLP server span per
        # request, continuing an inbound W3C traceparent when one is present.
        self._tracer = tracer
        # No metrics means metering is OFF. Configure a MetricsRegistry to record
        # the http.server.request.duration histogram, one point per request.
        self._metrics = metrics

    async def dispatch(
        self,
        method: str,
        path: str,
        body: bytes,
        authorization: str | None = None,
        traceparent: str | None = None,
    ) -> Response:
        # Both off is the cold path: one branch, no span, no clock read, byte for
        # byte the pre-observability behavior. Tracing and metering compose
        # independently, and a request is measured exactly once either way.
        if self._tracer is None and self._metrics is None:
            return await self._dispatch_inner(method, path, body, authorization)
        if self._tracer is None:
            return await self._dispatch_measured(method, path, body, authorization)
        return await self._dispatch_traced(method, path, body, authorization, traceparent)

    async def _dispatch_traced(
        self, method: str, path: str, body: bytes, authorization: str | None, traceparent: str | None
    ) -> Response:
        parent = parse_traceparent(traceparent)
        with self._tracer.start_span(
            f"{method} {_route_template(path)}",
            kind=KIND_SERVER,
            parent=parent,
            attributes={"http.request.method": method, "url.path": path},
        ) as span:
            response = await self._dispatch_measured(method, path, body, authorization)
            span.attributes["http.response.status_code"] = response.status
            # OTel maps a server span to error only on 5xx; a 4xx is the client's
            # fault and leaves the span status OK.
            if response.status >= 500:
                span.set_status(STATUS_ERROR, f"{response.status} {response.reason}")
            return response

    async def _dispatch_measured(
        self, method: str, path: str, body: bytes, authorization: str | None
    ) -> Response:
        """The single place a request is timed and recorded, so metering happens
        exactly once whether tracing is on or off (no double count)."""
        if self._metrics is None:
            return await self._dispatch_inner(method, path, body, authorization)
        start = self._metrics.now()
        response = await self._dispatch_inner(method, path, body, authorization)
        # The registry clock is epoch-wall, not monotonic; clamp a backward NTP
        # step to a non-negative duration, the same single-clock trade-off tracing
        # already accepts. _dispatch_inner never raises (it maps errors to a 500),
        # so a failed request is still recorded once, with its status.
        duration_seconds = max(0.0, (self._metrics.now() - start) / 1e9)
        self._metrics.record_request(
            method=method,
            route=self._metric_route(path),
            status_code=response.status,
            duration_seconds=duration_seconds,
        )
        return response

    def _metric_route(self, path: str) -> str | None:
        """The low-cardinality http.route metric attribute, or None for an
        unknown path so a flood of random 404 targets collapses into one no-route
        cell instead of unbounded series. The raw path is never a metric
        attribute (it stays the span's url.path)."""
        if path.startswith("/ledger/") or path.startswith("/replay/"):
            return _route_template(path)
        if path in _KNOWN_PATHS:
            return path
        return None

    async def _dispatch_inner(
        self, method: str, path: str, body: bytes, authorization: str | None
    ) -> Response:
        try:
            denied = self._authorize(method, path, authorization)
            if denied is not None:
                return denied
            return await self._route(method, path, body)
        except Exception as exc:  # never swallow: report with context
            return error(500, f"{type(exc).__name__}: {exc}")

    def _authorize(
        self, method: str, path: str, authorization: str | None
    ) -> Response | None:
        """Enforce bearer-JWT + scope for one request. Returns a 401/403 Response
        to reject, or None to allow. Authenticated decisions are witnessed in the
        ledger for a tamper-evident audit; unauthenticated 401s are not, so an
        unauthenticated flood cannot grow the audit log."""
        if self._verifier is None:
            return None
        scope = required_scope(method, path)
        if scope is None:
            return None  # public endpoint (for example /health)
        token = bearer_token(authorization)
        if token is None:
            return error(401, "missing bearer token")
        try:
            claims = self._verifier.verify(token)
        except InvalidToken as exc:
            return error(401, f"invalid token: {exc}")
        resource = f"{method} {path}"
        decision = authorize(claims, scope, self._role_policy)
        if not decision.granted:
            witness_authz(self._orch.ledger, decision, resource=resource)
            return error(403, decision.reason)
        if scope in _MUTATING_SCOPES:
            witness_authz(self._orch.ledger, decision, resource=resource)
        return None

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
        if method == "GET" and path == "/capsule":
            return self._capsule()
        if method == "GET" and path == "/room":
            return self._room()
        if method == "GET" and path == "/gates":
            return self._gates()
        if method == "POST" and path in ("/gate/approve", "/gate/edit", "/gate/reject"):
            return self._gate_resolve(path.rsplit("/", 1)[1], body)
        if method == "GET" and path == "/runtime":
            return self._runtime()
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
        if method == "POST" and path == "/context/preflight":
            return self._context_preflight(body)
        if method == "POST" and path == "/humanize":
            return self._humanize(body)
        if method == "POST" and path == "/prose/contract":
            return self._prose_contract(body)

        if path in _KNOWN_PATHS or path.startswith("/ledger/") or path.startswith("/replay/"):
            return error(405, f"method {method} not allowed for {path}")
        return error(404, f"no route for {path}")
