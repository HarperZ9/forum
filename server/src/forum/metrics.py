from __future__ import annotations

import bisect
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

# The stable OTel semantic-convention bucket boundaries for
# http.server.request.duration, in seconds, ascending. A value falls in bucket i
# where i is the count of boundaries it does not exceed (upper-inclusive, the
# Prometheus "le" convention), so a value equal to a boundary lands in the bucket
# that boundary closes.
DURATION_BUCKETS_SECONDS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0,
)

# OTLP AggregationTemporality CUMULATIVE, emitted as the bare integer. No delta
# path exists in this layer, so no DELTA constant is defined.
TEMPORALITY_CUMULATIVE = 2

# The one STABLE semconv instrument this registry emits. Name, unit, and
# description live here so the wire layer (forum.otlp) reads them from one place.
DURATION_METRIC_NAME = "http.server.request.duration"
DURATION_METRIC_UNIT = "s"
DURATION_METRIC_DESCRIPTION = "Duration of inbound HTTP server requests."


@dataclass(frozen=True, slots=True)
class HistogramPoint:
    """One cumulative histogram data point for a distinct attribute cell.

    ``attributes`` is a tuple of sorted ``(key, value)`` pairs, so an equal
    attribute set maps to one cell regardless of insertion order. ``bucket_counts``
    has one more entry than the registry's boundaries (the final overflow bucket).
    A collected point always has ``count >= 1``, so ``min`` and ``max`` are defined.
    """

    attributes: tuple[tuple[str, object], ...]
    count: int
    sum: float
    bucket_counts: tuple[int, ...]
    min: float
    max: float


class _Cell:
    """The mutable accumulator behind one HistogramPoint (one attribute set)."""

    __slots__ = ("count", "sum", "buckets", "min", "max")

    def __init__(self, n_buckets: int) -> None:
        self.count = 0
        self.sum = 0.0
        self.buckets = [0] * n_buckets
        self.min = 0.0
        self.max = 0.0

    def observe(self, value: float, idx: int) -> None:
        if self.count == 0:
            self.min = value
            self.max = value
        elif value < self.min:
            self.min = value
        elif value > self.max:
            self.max = value
        self.count += 1
        self.sum += value
        self.buckets[idx] += 1


class MetricsRegistry:
    """Accumulates the request-duration histogram in memory, cumulatively.

    Pure core: no OTLP-JSON knowledge and no network, exactly as ``Span`` stays
    free of wire concerns. The clock is injected (nanoseconds) for determinism,
    and a fixed CUMULATIVE start instant is captured once at construction, so
    every collected point reports the same ``start_unix_nano`` for the life of
    the process. Recording does a synchronous read-modify-write with no await, so
    under forum's single asyncio event loop no lock is needed.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], int] = time.time_ns,
        service_name: str = "forum",
        boundaries: Sequence[float] = DURATION_BUCKETS_SECONDS,
    ) -> None:
        self._clock = clock
        self.service_name = service_name
        self.boundaries = tuple(boundaries)
        self.start_unix_nano = clock()
        self._cells: dict[tuple[tuple[str, object], ...], _Cell] = {}

    def now(self) -> int:
        """The injected clock, in nanoseconds. The HTTP surface times a request
        with this so a test can share one clock and assert an exact duration."""
        return self._clock()

    def record_request(
        self,
        *,
        method: str,
        status_code: int,
        duration_seconds: float,
        route: str | None = None,
    ) -> None:
        """Observe one completed request into its attribute cell.

        The attribute set is the low-cardinality semconv trio: method, status
        code, and route. ``route`` is omitted when None, so unknown paths share a
        single no-route cell instead of one series per random target. Bucketing is
        upper-inclusive via ``bisect_left``.
        """
        attrs: list[tuple[str, object]] = [
            ("http.request.method", method),
            ("http.response.status_code", status_code),
        ]
        if route is not None:
            attrs.append(("http.route", route))
        key = tuple(sorted(attrs))
        cell = self._cells.get(key)
        if cell is None:
            cell = _Cell(len(self.boundaries) + 1)
            self._cells[key] = cell
        idx = bisect.bisect_left(self.boundaries, duration_seconds)
        cell.observe(duration_seconds, idx)

    def collect(self) -> list[HistogramPoint]:
        """A cumulative snapshot of every cell, sorted by attribute key for a
        stable order. Does NOT reset (cumulative temporality). Empty until a
        request is recorded."""
        return [
            HistogramPoint(
                attributes=key,
                count=cell.count,
                sum=cell.sum,
                bucket_counts=tuple(cell.buckets),
                min=cell.min,
                max=cell.max,
            )
            for key, cell in sorted(self._cells.items())
        ]
