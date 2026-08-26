import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from forum.otlp import OtlpHttpExporter, otlp_trace_payload, tracer_from_env
from forum.tracing import (
    KIND_SERVER,
    STATUS_ERROR,
    Span,
    SpanContext,
)


def _span(**over):
    base = dict(
        name="GET /status",
        context=SpanContext("a" * 32, "b" * 16, 1),
        parent_span_id=None,
        kind=KIND_SERVER,
        start_unix_nano=1000,
        end_unix_nano=2000,
    )
    base.update(over)
    return Span(**base)


def _only_span(payload):
    return payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]


def test_ids_are_hex_not_base64_and_nanos_are_strings():
    payload = otlp_trace_payload([_span()])
    span = _only_span(payload)
    # OTLP JSON overrides proto3's base64 default: ids stay hex strings.
    assert span["traceId"] == "a" * 32
    assert span["spanId"] == "b" * 16
    # proto3 int64 fields serialize as strings.
    assert span["startTimeUnixNano"] == "1000"
    assert span["endTimeUnixNano"] == "2000"


def test_resource_carries_service_name():
    payload = otlp_trace_payload([_span()], service_name="forum-api")
    attrs = payload["resourceSpans"][0]["resource"]["attributes"]
    assert {"key": "service.name", "value": {"stringValue": "forum-api"}} in attrs


def test_attribute_types_are_encoded_distinctly():
    span = _span(attributes={"s": "x", "n": 7, "b": True, "f": 1.5})
    encoded = {a["key"]: a["value"] for a in _only_span(otlp_trace_payload([span]))["attributes"]}
    assert encoded["s"] == {"stringValue": "x"}
    assert encoded["n"] == {"intValue": "7"}  # int64 -> string
    assert encoded["b"] == {"boolValue": True}  # bool before int (bool is an int)
    assert encoded["f"] == {"doubleValue": 1.5}


def test_parent_span_id_omitted_when_absent_and_present_when_set():
    assert "parentSpanId" not in _only_span(otlp_trace_payload([_span()]))
    withp = _only_span(otlp_trace_payload([_span(parent_span_id="c" * 16)]))
    assert withp["parentSpanId"] == "c" * 16


def test_error_status_is_encoded():
    span = _span(status_code=STATUS_ERROR, status_message="500 Internal Server Error")
    encoded = _only_span(otlp_trace_payload([span]))
    assert encoded["status"] == {"code": STATUS_ERROR, "message": "500 Internal Server Error"}


def test_exporter_posts_captured_payload_via_injected_transport():
    calls = []

    def transport(url, body, headers, timeout):
        calls.append((url, json.loads(body), headers))

    exporter = OtlpHttpExporter("http://collector:4318/", transport=transport)
    exporter.export([_span()])
    url, payload, headers = calls[0]
    assert url == "http://collector:4318/v1/traces"  # trailing slash normalized
    assert headers["Content-Type"] == "application/json"
    assert _only_span(payload)["traceId"] == "a" * 32


def test_exporter_swallows_transport_failure():
    def boom(*_):
        raise ConnectionError("collector down")

    # a telemetry outage must not raise into the traced request
    OtlpHttpExporter(transport=boom).export([_span()])


def test_empty_span_batch_makes_no_call():
    calls = []
    OtlpHttpExporter(transport=lambda *a: calls.append(a)).export([])
    assert calls == []


def test_tracer_from_env_is_none_without_an_endpoint():
    assert tracer_from_env({}) is None


def test_tracer_from_env_builds_an_otlp_tracer_from_standard_vars():
    calls = []
    tracer = tracer_from_env(
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318", "OTEL_SERVICE_NAME": "forum-api"}
    )
    assert tracer is not None and tracer.service_name == "forum-api"
    # swap in a recording transport to confirm the tracer's exporter targets /v1/traces
    tracer._exporter._transport = lambda url, *a: calls.append(url)
    with tracer.start_span("x"):
        pass
    assert calls == ["http://collector:4318/v1/traces"]


def test_emits_over_a_real_socket_to_an_otlp_endpoint():
    """End-to-end proof: the default urllib transport POSTs a well-formed OTLP
    body a collector's /v1/traces receiver would accept, over a real socket."""
    received: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received["path"] = self.path
            received["content_type"] = self.headers["Content-Type"]
            received["body"] = json.loads(self.rfile.read(length))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_):  # keep the test run quiet
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
        OtlpHttpExporter(endpoint, service_name="forum").export([_span()])
    finally:
        thread.join(timeout=5)
        server.server_close()

    assert received["path"] == "/v1/traces"
    assert received["content_type"] == "application/json"
    assert _only_span(received["body"])["spanId"] == "b" * 16
