"""Forum: OTLP tracing that emits a real span (v0.6).

Runs two requests through the HTTP surface with tracing on. The first is a
root request; the second carries a W3C ``traceparent`` header, so its server
span continues the caller's trace. Both are shown as the exact OTLP/HTTP JSON a
collector's ``/v1/traces`` receiver accepts, and the payload is written to
benchmarks/otlp_trace_sample.json as an inspectable receipt.

If OTEL_EXPORTER_OTLP_ENDPOINT is set (for example http://localhost:4318), the
spans are also POSTed there over a real socket, exactly as ``forum serve`` does.

Run:  python examples/run_tracing.py        # zero dependencies, no install needed
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import pathlib
import sys

# Make `forum` importable straight from a checkout (src layout), no install needed.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.engine import Orchestrator
from forum.executor import EchoExecutor
from forum.http_surface import HttpSurface
from forum.ledger import InMemoryStorage, Ledger
from forum.otlp import otlp_trace_payload
from forum.policy import Policy
from forum.roster import load_default
from forum.tracing import InMemorySpanExporter, SpanContext, Tracer, format_traceparent


def rule(title: str) -> None:
    print("\n" + title)
    print("-" * len(title))


def build_surface(exporter: InMemorySpanExporter) -> HttpSurface:
    ledger = Ledger(InMemoryStorage())
    orch = Orchestrator(
        load_default(), ledger, EchoExecutor(),
        Policy(allowed_categories=frozenset({"engineering", "graphics", "support", "research"})),
    )
    # Deterministic clock + id source so the committed sample is byte-stable and
    # reproducible; production uses the defaults (time.time_ns, os.urandom).
    ids = itertools.count(1)
    clock = itertools.count(1_000_000_000)
    tracer = Tracer(
        exporter,
        clock=lambda: next(clock),
        id_source=lambda n: next(ids).to_bytes(n, "big"),
        service_name="forum",
    )
    return HttpSurface(orch, tracer=tracer)


def main() -> int:
    exporter = InMemorySpanExporter()
    surface = build_surface(exporter)

    rule("A root request")
    asyncio.run(surface.dispatch("GET", "/status", b""))
    root = exporter.spans[-1]
    print(f"trace_id={root.context.trace_id}  span_id={root.context.span_id}  parent={root.parent_span_id}")

    rule("A request that continues a caller's trace")
    caller = SpanContext("a" * 32, "b" * 16, 1)
    header = format_traceparent(caller)
    print(f"inbound traceparent: {header}")
    asyncio.run(surface.dispatch("GET", "/health", b"", None, header))
    child = exporter.spans[-1]
    print(f"trace_id={child.context.trace_id}  span_id={child.context.span_id}  parent={child.parent_span_id}")
    assert child.context.trace_id == caller.trace_id
    assert child.parent_span_id == caller.span_id
    print("-> same trace as the caller, linked to the caller's span")

    payload = otlp_trace_payload(exporter.spans, service_name="forum")
    out = pathlib.Path(__file__).resolve().parent.parent / "benchmarks" / "otlp_trace_sample.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    rule("OTLP/HTTP JSON payload")
    print(f"{len(exporter.spans)} spans -> {out.relative_to(out.parent.parent)}")

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        from forum.otlp import OtlpHttpExporter

        OtlpHttpExporter(endpoint, service_name="forum").export(exporter.spans)
        print(f"also POSTed {len(exporter.spans)} spans to {endpoint.rstrip('/')}/v1/traces")
    else:
        print("set OTEL_EXPORTER_OTLP_ENDPOINT to also emit to a live collector")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
