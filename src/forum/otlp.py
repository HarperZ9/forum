from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable, Mapping, Sequence

from forum.tracing import Span, Tracer

_SCOPE_NAME = "forum.tracing"
_SCOPE_VERSION = "1"

# A transport takes (url, body, headers, timeout) and performs the POST. The
# default hits the network; tests inject one that records the call instead.
Transport = Callable[[str, bytes, Mapping[str, str], float], None]


def _any_value(value: object) -> dict:
    """Encode a Python value as an OTLP AnyValue. bool is checked before int
    because bool is an int subclass and OTLP has a distinct boolValue."""
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        # int64 fields serialize as strings in proto3 JSON; AnyValue.intValue too.
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": str(value)}


def _attributes(attrs: Mapping[str, object]) -> list[dict]:
    return [{"key": k, "value": _any_value(v)} for k, v in attrs.items()]


def _span_json(span: Span) -> dict:
    """Map one Span to an OTLP JSON Span object.

    trace/span ids stay hex strings (the OTLP-JSON rule that overrides proto3's
    base64 default for these two byte fields), and the UnixNano timestamps are
    strings (proto3 int64 mapping). An open span (no end) is closed at its start
    instant so the export is always well formed.
    """
    out: dict = {
        "traceId": span.context.trace_id,
        "spanId": span.context.span_id,
        "name": span.name,
        "kind": span.kind,
        "startTimeUnixNano": str(span.start_unix_nano),
        "endTimeUnixNano": str(
            span.end_unix_nano if span.end_unix_nano is not None else span.start_unix_nano
        ),
        "attributes": _attributes(span.attributes),
    }
    if span.parent_span_id:
        out["parentSpanId"] = span.parent_span_id
    if span.status_code:
        status: dict = {"code": span.status_code}
        if span.status_message:
            status["message"] = span.status_message
        out["status"] = status
    if span.events:
        out["events"] = [
            {
                "name": e.name,
                "timeUnixNano": str(e.time_unix_nano),
                "attributes": _attributes(e.attributes),
            }
            for e in span.events
        ]
    return out


def otlp_trace_payload(
    spans: Sequence[Span],
    *,
    service_name: str = "forum",
    scope_name: str = _SCOPE_NAME,
) -> dict:
    """Build one OTLP ExportTraceServiceRequest body as a JSON-ready dict.

    The shape a collector's ``/v1/traces`` receiver accepts:
    resourceSpans[].scopeSpans[].spans[], with the resource carrying
    ``service.name``. Serialize it with ``json.dumps`` and POST as
    ``application/json``.
    """
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": _attributes({"service.name": service_name})},
                "scopeSpans": [
                    {
                        "scope": {"name": scope_name, "version": _SCOPE_VERSION},
                        "spans": [_span_json(s) for s in spans],
                    }
                ],
            }
        ]
    }


def _http_post(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> None:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


class OtlpHttpExporter:
    """Emits spans to an OTLP/HTTP JSON collector at ``<endpoint>/v1/traces``.

    This is the one place forum's tracing touches the network, so it lives here
    as an edge adapter and the pure core never imports it. It POSTs
    ``application/json`` with urllib; a stock OpenTelemetry Collector's OTLP
    receiver ingests the body unchanged. Export failures are swallowed on
    purpose: a telemetry backend outage must never break the request being
    measured. Inject ``transport`` to capture the POST without a socket.
    """

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:4318",
        *,
        service_name: str = "forum",
        headers: Mapping[str, str] | None = None,
        timeout: float = 5.0,
        transport: Transport | None = None,
    ) -> None:
        self._url = endpoint.rstrip("/") + "/v1/traces"
        self._service_name = service_name
        self._headers = {"Content-Type": "application/json", **dict(headers or {})}
        self._timeout = timeout
        self._transport = transport or _http_post

    @property
    def url(self) -> str:
        return self._url

    def export(self, spans: Sequence[Span]) -> None:
        if not spans:
            return
        payload = otlp_trace_payload(spans, service_name=self._service_name)
        body = json.dumps(payload).encode("utf-8")
        try:
            self._transport(self._url, body, self._headers, self._timeout)
        except Exception:
            # Telemetry is best-effort: a collector that is down, slow, or
            # rejecting must not surface as an error on the traced request.
            return


def tracer_from_env(env: Mapping[str, str] | None = None) -> Tracer | None:
    """Build a Tracer that emits to the OTLP endpoint named by the environment.

    Reads the standard ``OTEL_EXPORTER_OTLP_ENDPOINT`` (the collector base URL,
    for example ``http://localhost:4318``; the ``/v1/traces`` path is appended)
    and ``OTEL_SERVICE_NAME`` (default ``forum``). Returns None when no endpoint
    is set, so tracing stays off until an operator points the daemon at a
    collector. This is how ``forum serve`` turns emission on with no code change.
    """
    env = os.environ if env is None else env
    endpoint = env.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None
    service = env.get("OTEL_SERVICE_NAME") or "forum"
    return Tracer(OtlpHttpExporter(endpoint, service_name=service), service_name=service)
