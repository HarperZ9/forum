import asyncio
import itertools

from forum.engine import Orchestrator
from forum.executor import EchoExecutor
from forum.http_surface import HttpSurface
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.roster import load_default
from forum.tracing import (
    KIND_SERVER,
    STATUS_ERROR,
    STATUS_OK,
    InMemorySpanExporter,
    SpanContext,
    Tracer,
    format_traceparent,
)

ALL = frozenset({"engineering", "graphics", "support", "research"})


def _orch():
    ticks = iter(float(t) for t in range(1, 100_000))
    ledger = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    return Orchestrator(
        load_default(), ledger, EchoExecutor(),
        Policy(allowed_categories=ALL, max_parallel=4),
    )


def _traced_surface():
    exporter = InMemorySpanExporter()
    ids = itertools.count(1)
    clock = itertools.count(1000)
    tracer = Tracer(
        exporter,
        clock=lambda: next(clock),
        id_source=lambda n: next(ids).to_bytes(n, "big"),
    )
    return HttpSurface(_orch(), tracer=tracer), exporter


def _do(surface, method, path, body=b"", traceparent=None):
    return asyncio.run(surface.dispatch(method, path, body, None, traceparent))


def test_no_tracer_records_no_span_and_still_serves():
    surface = HttpSurface(_orch())  # tracing off
    assert _do(surface, "GET", "/health").status == 200


def test_request_emits_a_server_span_with_http_attributes():
    surface, exporter = _traced_surface()
    resp = _do(surface, "GET", "/status")
    assert resp.status == 200
    span = exporter.spans[0]
    assert span.name == "GET /status"
    assert span.kind == KIND_SERVER
    assert span.attributes["http.request.method"] == "GET"
    assert span.attributes["url.path"] == "/status"
    assert span.attributes["http.response.status_code"] == 200
    assert span.status_code == STATUS_OK


def test_inbound_traceparent_continues_the_trace():
    surface, exporter = _traced_surface()
    parent = SpanContext("a" * 32, "d" * 16, 1)
    _do(surface, "GET", "/health", traceparent=format_traceparent(parent))
    span = exporter.spans[0]
    assert span.context.trace_id == parent.trace_id
    assert span.parent_span_id == parent.span_id


def test_variable_seq_path_is_templated_in_the_span_name():
    surface, exporter = _traced_surface()
    _do(surface, "GET", "/ledger/0")
    span = exporter.spans[0]
    assert span.name == "GET /ledger/{seq}"  # low-cardinality name
    assert span.attributes["url.path"] == "/ledger/0"  # raw path preserved


def test_server_error_marks_the_span_error_but_client_error_does_not():
    surface, exporter = _traced_surface()
    # unknown route -> 404 (client fault): span stays OK
    _do(surface, "GET", "/no-such-route")
    assert exporter.spans[0].status_code == STATUS_OK
    assert exporter.spans[0].attributes["http.response.status_code"] == 404
    # /plan under EchoExecutor returns 502 (server fault): span is error
    exporter.clear()
    _do(surface, "POST", "/plan", b'{"request": "x"}')
    span = exporter.spans[0]
    assert span.attributes["http.response.status_code"] == 502
    assert span.status_code == STATUS_ERROR
