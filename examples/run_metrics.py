"""Forum: OTLP metrics that emit a real duration histogram (v0.6).

Records a spread of requests into the one stable semconv instrument,
http.server.request.duration (a cumulative explicit-bucket histogram), across a
few attribute cells, then shows the exact OTLP/HTTP JSON a collector's
/v1/metrics receiver accepts. The payload is written to
benchmarks/otlp_metrics_sample.json as an inspectable, byte-stable receipt.

If OTEL_EXPORTER_OTLP_ENDPOINT is set (for example http://localhost:4318), the
metrics are also POSTed there over a real socket, exactly as `forum serve` does
on shutdown.

Run:  python examples/run_metrics.py        # zero dependencies, no install needed
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

# Make `forum` importable straight from a checkout (src layout), no install needed.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.metrics import MetricsRegistry
from forum.otlp_metrics import otlp_metrics_payload

# A fixed clock so the committed sample is byte-stable and reproducible;
# production uses the default time.time_ns.
_START_NS = 1_000_000_000
_NOW_NS = _START_NS + 60_000_000_000  # 60 seconds later


def rule(title: str) -> None:
    print("\n" + title)
    print("-" * len(title))


def main() -> int:
    registry = MetricsRegistry(clock=lambda: _START_NS, service_name="forum")

    # A realistic spread: mostly-fast GETs, one slow tail, one server error, and
    # a POST on another route, so the histogram shows several buckets and cells.
    for d in (0.003, 0.02, 0.4, 0.42, 1.2):
        registry.record_request(method="GET", status_code=200, duration_seconds=d, route="/status")
    registry.record_request(method="GET", status_code=500, duration_seconds=3.0, route="/status")
    registry.record_request(method="POST", status_code=200, duration_seconds=0.6, route="/submit")

    rule("Recorded cells (cumulative)")
    for p in registry.collect():
        attrs = dict(p.attributes)
        print(
            f"{attrs['http.request.method']:4} {attrs.get('http.route',''):8} "
            f"status={attrs['http.response.status_code']}  "
            f"count={p.count} sum={p.sum:.3f}s min={p.min:.3f} max={p.max:.3f}"
        )

    payload = otlp_metrics_payload(registry, now_unix_nano=_NOW_NS)
    out = pathlib.Path(__file__).resolve().parent.parent / "benchmarks" / "otlp_metrics_sample.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    rule("OTLP/HTTP JSON payload")
    n_points = len(payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"][0]["histogram"]["dataPoints"])
    print(f"{n_points} data points -> {out.relative_to(out.parent.parent)}")

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        from forum.otlp_metrics import OtlpHttpMetricExporter

        OtlpHttpMetricExporter(endpoint).export(registry, now_unix_nano=_NOW_NS)
        print(f"also POSTed the histogram to {endpoint.rstrip('/')}/v1/metrics")
    else:
        print("set OTEL_EXPORTER_OTLP_ENDPOINT to also emit to a live collector")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
