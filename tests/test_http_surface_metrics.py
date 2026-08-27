import asyncio
import itertools

from forum.engine import Orchestrator
from forum.executor import EchoExecutor
from forum.http_surface import HttpSurface
from forum.ledger import InMemoryStorage, Ledger
from forum.metrics import MetricsRegistry
from forum.policy import Policy
from forum.roster import load_default
from forum.tracing import InMemorySpanExporter, Tracer

ALL = frozenset({"engineering", "graphics", "support", "research"})


def _orch():
    ticks = iter(float(t) for t in range(1, 100_000))
    ledger = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    return Orchestrator(
        load_default(), ledger, EchoExecutor(),
        Policy(allowed_categories=ALL, max_parallel=4),
    )


def _metrics_clock(start_ns, step_ns):
    # construction reads once, then each request reads twice (start, end); a fixed
    # per-read step makes every request's duration exactly step_ns nanoseconds.
    counter = itertools.count(start_ns, step_ns)
    return lambda: next(counter)


def _metered_surface(step_ns=500_000_000, boundaries=(1.0, 2.0)):
    # step 0.5s per read -> each request lasts 0.5s (end - start)
    registry = MetricsRegistry(clock=_metrics_clock(0, step_ns), boundaries=boundaries)
    return HttpSurface(_orch(), metrics=registry), registry


def _do(surface, method, path, body=b""):
    return asyncio.run(surface.dispatch(method, path, body))


def test_no_metrics_records_nothing_and_still_serves():
    surface = HttpSurface(_orch())  # metering off
    assert _do(surface, "GET", "/health").status == 200


def test_one_point_per_request_with_method_route_status():
    surface, reg = _metered_surface()
    assert _do(surface, "GET", "/status").status == 200
    points = reg.collect()
    assert len(points) == 1
    attrs = dict(points[0].attributes)
    assert attrs == {
        "http.request.method": "GET",
        "http.response.status_code": 200,
        "http.route": "/status",
    }
    assert points[0].count == 1


def test_duration_from_injected_clock_lands_in_the_right_bucket():
    # each request lasts 0.5s; with boundaries (1,2) that is bucket 0 ((-inf,1])
    surface, reg = _metered_surface(step_ns=500_000_000, boundaries=(1.0, 2.0))
    _do(surface, "GET", "/status")
    p = reg.collect()[0]
    assert p.bucket_counts == (1, 0, 0)
    assert p.sum == 0.5


def test_unknown_path_records_without_a_route_attribute():
    surface, reg = _metered_surface()
    assert _do(surface, "GET", "/no-such-route").status == 404
    p = reg.collect()[0]
    assert "http.route" not in dict(p.attributes)  # 404 flood collapses to one cell
    assert dict(p.attributes)["http.response.status_code"] == 404


def test_variable_seq_path_is_templated_in_metric_route():
    surface, reg = _metered_surface()
    _do(surface, "GET", "/ledger/0")
    assert dict(reg.collect()[0].attributes)["http.route"] == "/ledger/{seq}"


def test_server_error_is_recorded_with_its_status():
    surface, reg = _metered_surface()
    _do(surface, "POST", "/plan", b'{"request": "x"}')  # 502 under EchoExecutor
    assert dict(reg.collect()[0].attributes)["http.response.status_code"] == 502


def test_backward_clock_step_clamps_duration_to_zero():
    # construction reads 0, request start reads 1.0s, request end reads 0.5s (an
    # NTP step back). The raw delta is negative; it must be clamped to 0.0.
    reads = iter([0, 1_000_000_000, 500_000_000])
    registry = MetricsRegistry(clock=lambda: next(reads), boundaries=(1.0, 2.0))
    surface = HttpSurface(_orch(), metrics=registry)
    asyncio.run(surface.dispatch("GET", "/status", b""))
    p = registry.collect()[0]
    assert p.sum == 0.0  # negative delta clamped, not recorded as negative
    assert p.bucket_counts == (1, 0, 0)  # 0.0 falls in the first bucket


def test_tracing_and_metrics_compose_with_no_double_count():
    exporter = InMemorySpanExporter()
    ids = itertools.count(1)
    tracer = Tracer(exporter, clock=itertools.count(1000).__next__,
                    id_source=lambda n: next(ids).to_bytes(n, "big"))
    registry = MetricsRegistry(clock=_metrics_clock(0, 500_000_000), boundaries=(1.0, 2.0))
    surface = HttpSurface(_orch(), tracer=tracer, metrics=registry)
    asyncio.run(surface.dispatch("GET", "/status", b""))
    assert len(exporter.spans) == 1  # one span
    assert registry.collect()[0].count == 1  # and exactly one metric point
