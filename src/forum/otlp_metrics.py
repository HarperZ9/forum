from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence

from forum.metrics import (
    DURATION_METRIC_DESCRIPTION,
    DURATION_METRIC_NAME,
    DURATION_METRIC_UNIT,
    TEMPORALITY_CUMULATIVE,
    HistogramPoint,
    MetricsRegistry,
)
# The metrics wire layer reuses the trace layer's OTLP primitives (attribute
# encoding, the POST transport seam, the scope version) so both signals share one
# encoding and one network path.
from forum.otlp import _SCOPE_VERSION, Transport, _attributes, _http_post

_METRICS_SCOPE_NAME = "forum.metrics"


def _histogram_data_point(
    point: HistogramPoint,
    boundaries: Sequence[float],
    start_unix_nano: int,
    time_unix_nano: int,
) -> dict:
    """Map one HistogramPoint to an OTLP HistogramDataPoint.

    The OTLP-JSON encodings that differ from stock proto3 JSON: count and every
    bucketCounts entry are uint64 fields, so they are strings; sum, min, max, and
    the explicitBounds are doubles, so they are JSON numbers; the *UnixNano fields
    are fixed64, so strings.
    """
    return {
        "attributes": _attributes(dict(point.attributes)),
        "startTimeUnixNano": str(start_unix_nano),
        "timeUnixNano": str(time_unix_nano),
        "count": str(point.count),
        "sum": point.sum,
        "bucketCounts": [str(c) for c in point.bucket_counts],
        "explicitBounds": list(boundaries),
        "min": point.min,
        "max": point.max,
    }


def otlp_metrics_payload(
    registry: MetricsRegistry,
    *,
    now_unix_nano: int | None = None,
    scope_name: str = _METRICS_SCOPE_NAME,
    points: Sequence[HistogramPoint] | None = None,
) -> dict:
    """Build one OTLP ExportMetricsServiceRequest body as a JSON-ready dict.

    Emits the single cumulative explicit-bucket Histogram
    (``http.server.request.duration``) a collector's ``/v1/metrics`` receiver
    accepts. ``aggregationTemporality`` is the bare integer 2 (CUMULATIVE), and a
    Histogram carries no ``isMonotonic`` field. ``service.name`` is read from the
    registry, so it cannot drift from what recorded the points. Defaults the data
    point's ``timeUnixNano`` to the registry clock. Pass ``points`` to reuse an
    already-collected snapshot instead of collecting again.
    """
    now = registry.now() if now_unix_nano is None else now_unix_nano
    if points is None:
        points = registry.collect()
    data_points = [
        _histogram_data_point(p, registry.boundaries, registry.start_unix_nano, now)
        for p in points
    ]
    return {
        "resourceMetrics": [
            {
                "resource": {"attributes": _attributes({"service.name": registry.service_name})},
                "scopeMetrics": [
                    {
                        "scope": {"name": scope_name, "version": _SCOPE_VERSION},
                        "metrics": [
                            {
                                "name": DURATION_METRIC_NAME,
                                "unit": DURATION_METRIC_UNIT,
                                "description": DURATION_METRIC_DESCRIPTION,
                                "histogram": {
                                    "aggregationTemporality": TEMPORALITY_CUMULATIVE,
                                    "dataPoints": data_points,
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }


class OtlpHttpMetricExporter:
    """Emits the request-duration histogram to an OTLP/HTTP JSON collector at
    ``<endpoint>/v1/metrics``.

    The metrics twin of OtlpHttpExporter, and an edge adapter for the same
    reason: it POSTs ``application/json`` with urllib and swallows failures, so a
    telemetry outage never breaks the daemon. ``service_name`` is not a
    constructor argument here; it comes from the registry at export time, which
    keeps a single source of truth. Inject ``transport`` to capture the POST
    without a socket.
    """

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:4318",
        *,
        headers: Mapping[str, str] | None = None,
        timeout: float = 5.0,
        transport: Transport | None = None,
    ) -> None:
        self._url = endpoint.rstrip("/") + "/v1/metrics"
        self._headers = {"Content-Type": "application/json", **dict(headers or {})}
        self._timeout = timeout
        self._transport = transport or _http_post

    @property
    def url(self) -> str:
        return self._url

    def export(self, registry: MetricsRegistry, *, now_unix_nano: int | None = None) -> None:
        points = registry.collect()
        if not points:
            return  # nothing recorded yet; do not POST an empty histogram
        body = json.dumps(
            otlp_metrics_payload(registry, now_unix_nano=now_unix_nano, points=points)
        ).encode("utf-8")
        try:
            self._transport(self._url, body, self._headers, self._timeout)
        except Exception:
            # Best-effort, exactly as the trace exporter: a collector that is
            # down or slow must not surface as an error on shutdown.
            return


def meter_from_env(
    env: Mapping[str, str] | None = None,
) -> tuple[MetricsRegistry, OtlpHttpMetricExporter] | None:
    """Build a (MetricsRegistry, OtlpHttpMetricExporter) from the standard OTLP
    environment, or None when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is unset.

    Mirrors ``tracer_from_env``: it reads the collector base URL (the
    ``/v1/metrics`` path is appended) and ``OTEL_SERVICE_NAME`` (default
    ``forum``). This is how ``forum serve`` turns metric emission on with no code
    change. The daemon passes the one registry to both the surface (to record)
    and the exporter (to flush).
    """
    env = os.environ if env is None else env
    endpoint = env.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return None
    service = env.get("OTEL_SERVICE_NAME") or "forum"
    return MetricsRegistry(service_name=service), OtlpHttpMetricExporter(endpoint)
