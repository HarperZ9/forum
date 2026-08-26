import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from forum.metrics import MetricsRegistry
from forum.otlp_metrics import (
    OtlpHttpMetricExporter,
    meter_from_env,
    otlp_metrics_payload,
)


def _metrics_reg(boundaries=(1.0, 2.0), start=1000):
    reg = MetricsRegistry(clock=lambda: start, service_name="forum", boundaries=boundaries)
    reg.record_request(method="GET", status_code=200, duration_seconds=1.5, route="/status")
    return reg


def _metric(payload):
    return payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]


def _mdp(payload):
    return _metric(payload)["histogram"]["dataPoints"][0]


def test_metric_payload_shape_and_scope():
    payload = otlp_metrics_payload(_metrics_reg(), now_unix_nano=2000)
    scope = payload["resourceMetrics"][0]["scopeMetrics"][0]["scope"]
    assert scope["name"] == "forum.metrics"
    metric = _metric(payload)
    assert metric["name"] == "http.server.request.duration"
    assert metric["unit"] == "s"
    assert "histogram" in metric and "sum" not in metric  # a Histogram, not a Sum


def test_resource_service_name_comes_from_the_registry():
    reg = MetricsRegistry(clock=lambda: 1, service_name="forum-metering")
    reg.record_request(method="GET", status_code=200, duration_seconds=0.5)
    attrs = otlp_metrics_payload(reg)["resourceMetrics"][0]["resource"]["attributes"]
    assert {"key": "service.name", "value": {"stringValue": "forum-metering"}} in attrs


def test_temporality_is_bare_int_two_and_no_is_monotonic():
    hist = _metric(otlp_metrics_payload(_metrics_reg(), now_unix_nano=2000))["histogram"]
    assert hist["aggregationTemporality"] == 2  # CUMULATIVE, bare integer not a string
    assert "isMonotonic" not in hist  # Histogram has no such field


def test_int64_fields_are_strings_and_double_fields_are_numbers():
    dp = _mdp(otlp_metrics_payload(_metrics_reg(), now_unix_nano=2000))
    # uint64 / fixed64 -> JSON strings
    assert dp["startTimeUnixNano"] == "1000" and dp["timeUnixNano"] == "2000"
    assert dp["count"] == "1"
    assert dp["bucketCounts"] == ["0", "1", "0"]  # 1.5 in bucket 1 of (1,2]
    assert all(isinstance(c, str) for c in dp["bucketCounts"])
    # doubles -> JSON numbers
    assert dp["sum"] == 1.5 and dp["min"] == 1.5 and dp["max"] == 1.5
    assert dp["explicitBounds"] == [1.0, 2.0]
    assert all(isinstance(b, float) for b in dp["explicitBounds"])


def test_bucket_counts_length_is_bounds_plus_one_and_sums_to_count():
    dp = _mdp(otlp_metrics_payload(_metrics_reg(), now_unix_nano=2000))
    assert len(dp["bucketCounts"]) == len(dp["explicitBounds"]) + 1
    assert sum(int(c) for c in dp["bucketCounts"]) == int(dp["count"])


def test_status_code_attribute_is_intvalue_string():
    attrs = {a["key"]: a["value"] for a in _mdp(otlp_metrics_payload(_metrics_reg(), now_unix_nano=2000))["attributes"]}
    assert attrs["http.request.method"] == {"stringValue": "GET"}
    assert attrs["http.response.status_code"] == {"intValue": "200"}
    assert attrs["http.route"] == {"stringValue": "/status"}


def test_payload_encodes_multiple_cells_in_sorted_order():
    reg = MetricsRegistry(clock=lambda: 1000, service_name="forum", boundaries=(1.0, 2.0))
    reg.record_request(method="GET", status_code=200, duration_seconds=0.5, route="/status")
    reg.record_request(method="POST", status_code=500, duration_seconds=1.5, route="/submit")
    dps = _metric(otlp_metrics_payload(reg, now_unix_nano=2000))["histogram"]["dataPoints"]
    assert len(dps) == 2  # the N-cell mapping, not just N=1
    methods = [
        {a["key"]: a["value"] for a in dp["attributes"]}["http.request.method"]["stringValue"]
        for dp in dps
    ]
    assert methods == ["GET", "POST"]  # collect() sorts by attribute key


def test_metric_exporter_posts_to_v1_metrics_via_injected_transport():
    calls = []
    OtlpHttpMetricExporter("http://collector:4318/", transport=lambda u, b, h, t: calls.append((u, json.loads(b)))).export(
        _metrics_reg(), now_unix_nano=2000
    )
    url, payload = calls[0]
    assert url == "http://collector:4318/v1/metrics"  # trailing slash normalized
    assert _metric(payload)["name"] == "http.server.request.duration"


def test_metric_exporter_skips_empty_registry():
    calls = []
    OtlpHttpMetricExporter(transport=lambda *a: calls.append(a)).export(MetricsRegistry(clock=lambda: 1))
    assert calls == []  # nothing recorded -> no POST of an empty histogram


def test_metric_exporter_swallows_transport_failure():
    def boom(*_):
        raise ConnectionError("collector down")

    OtlpHttpMetricExporter(transport=boom).export(_metrics_reg())  # must not raise


def test_meter_from_env_none_without_endpoint_and_built_with_it():
    assert meter_from_env({}) is None
    built = meter_from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://c:4318", "OTEL_SERVICE_NAME": "svc"})
    assert built is not None
    registry, exporter = built
    assert registry.service_name == "svc"
    assert exporter.url == "http://c:4318/v1/metrics"


def test_metrics_emit_over_a_real_socket_to_a_v1_metrics_endpoint():
    received: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received["path"] = self.path
            received["body"] = json.loads(self.rfile.read(length))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    try:
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
        OtlpHttpMetricExporter(endpoint).export(_metrics_reg(), now_unix_nano=2000)
    finally:
        thread.join(timeout=5)
        server.server_close()

    assert not thread.is_alive(), "collector never received the request"
    assert received["path"] == "/v1/metrics"
    assert _metric(received["body"])["name"] == "http.server.request.duration"
