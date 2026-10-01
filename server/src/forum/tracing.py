from __future__ import annotations

import contextlib
import os
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

# Span kinds mirror the OTLP SpanKind enum, so an exporter maps them with no
# lookup table: 1 internal, 2 server, 3 client, 4 producer, 5 consumer.
KIND_INTERNAL = 1
KIND_SERVER = 2
KIND_CLIENT = 3
KIND_PRODUCER = 4
KIND_CONSUMER = 5

# Status codes mirror OTLP Status.StatusCode: 0 unset, 1 ok, 2 error.
STATUS_UNSET = 0
STATUS_OK = 1
STATUS_ERROR = 2

_TRACE_ID_HEX = 32
_SPAN_ID_HEX = 16
_ZERO_TRACE = "0" * _TRACE_ID_HEX
_ZERO_SPAN = "0" * _SPAN_ID_HEX
_HEX_DIGITS = frozenset("0123456789abcdef")


def _is_hex(s: str) -> bool:
    return bool(s) and all(c in _HEX_DIGITS for c in s)


@dataclass(frozen=True, slots=True)
class SpanContext:
    """A W3C-shaped span identity: 16-byte trace id, 8-byte span id, 1-byte flags.

    Ids are lowercase hex (32 and 16 chars). ``trace_flags`` bit 0 is the sampled
    flag; ``sampled`` reads it. ``format_traceparent`` / ``parse_traceparent``
    move a context across a process boundary as the W3C ``traceparent`` header.
    """

    trace_id: str
    span_id: str
    trace_flags: int = 1  # sampled by default

    @property
    def sampled(self) -> bool:
        return bool(self.trace_flags & 0x01)

    def is_valid(self) -> bool:
        return (
            len(self.trace_id) == _TRACE_ID_HEX
            and self.trace_id != _ZERO_TRACE
            and _is_hex(self.trace_id)
            and len(self.span_id) == _SPAN_ID_HEX
            and self.span_id != _ZERO_SPAN
            and _is_hex(self.span_id)
        )


def format_traceparent(ctx: SpanContext) -> str:
    """Render a SpanContext as a W3C ``traceparent`` header (version 00)."""
    return f"00-{ctx.trace_id}-{ctx.span_id}-{ctx.trace_flags & 0xFF:02x}"


def parse_traceparent(header: str | None) -> SpanContext | None:
    """Parse a W3C ``traceparent`` header into a SpanContext, or None if unusable.

    Accepts version 00 and tolerates a higher version's leading four fields, per
    the spec's forward-compatibility rule. A malformed, ``ff``-versioned, or
    all-zero id returns None rather than a bogus parent, so a bad header simply
    starts a fresh trace instead of corrupting one.
    """
    if not header:
        return None
    parts = header.strip().split("-")
    if len(parts) < 4:
        return None
    version, trace_id, span_id, flags = parts[0], parts[1].lower(), parts[2].lower(), parts[3]
    if len(version) != 2 or not _is_hex(version) or version == "ff":
        return None
    if len(trace_id) != _TRACE_ID_HEX or len(span_id) != _SPAN_ID_HEX:
        return None
    if not _is_hex(trace_id) or not _is_hex(span_id):
        return None
    if trace_id == _ZERO_TRACE or span_id == _ZERO_SPAN:
        return None
    if len(flags) < 2 or not _is_hex(flags[:2]):
        return None
    return SpanContext(trace_id, span_id, int(flags[:2], 16))


@dataclass(frozen=True, slots=True)
class SpanEvent:
    name: str
    time_unix_nano: int
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class Span:
    """One unit of work, shaped for OTLP export.

    Mutable while in flight: the instrumentation that opened the span sets
    attributes and status before it ends. ``end_unix_nano`` is None until the
    span closes.
    """

    name: str
    context: SpanContext
    parent_span_id: str | None
    kind: int
    start_unix_nano: int
    end_unix_nano: int | None = None
    attributes: dict[str, object] = field(default_factory=dict)
    events: list[SpanEvent] = field(default_factory=list)
    status_code: int = STATUS_UNSET
    status_message: str = ""

    def set_status(self, code: int, message: str = "") -> None:
        self.status_code = code
        self.status_message = message

    def add_event(self, name: str, time_unix_nano: int, **attributes: object) -> None:
        self.events.append(SpanEvent(name, time_unix_nano, dict(attributes)))


class SpanExporter(Protocol):
    def export(self, spans: Sequence[Span]) -> None: ...


class NullSpanExporter:
    """Drops spans. The default, so an unconfigured tracer costs only id bytes."""

    def export(self, spans: Sequence[Span]) -> None:
        return None


class InMemorySpanExporter:
    """Keeps finished spans in a list, for tests and in-process inspection."""

    def __init__(self) -> None:
        self.spans: list[Span] = []

    def export(self, spans: Sequence[Span]) -> None:
        self.spans.extend(spans)

    def clear(self) -> None:
        self.spans.clear()


class Tracer:
    """Creates and times spans, then hands finished spans to an exporter.

    Determinism is by injection: pass ``clock`` (a nanosecond source) and
    ``id_source`` (n random bytes) and every id and timestamp is reproducible in
    a test. The defaults (``time.time_ns``, ``os.urandom``) give real, unique
    ids in production. The tracer holds no ambient state, so it is safe to share
    across concurrent requests.
    """

    def __init__(
        self,
        exporter: SpanExporter | None = None,
        *,
        clock: Callable[[], int] = time.time_ns,
        id_source: Callable[[int], bytes] = os.urandom,
        service_name: str = "forum",
    ) -> None:
        self._exporter = exporter or NullSpanExporter()
        self._clock = clock
        self._id_source = id_source
        self.service_name = service_name

    def new_trace_id(self) -> str:
        return self._id_source(16).hex()

    def new_span_id(self) -> str:
        return self._id_source(8).hex()

    @contextlib.contextmanager
    def start_span(
        self,
        name: str,
        *,
        kind: int = KIND_INTERNAL,
        parent: SpanContext | None = None,
        attributes: Mapping[str, object] | None = None,
    ) -> Iterator[Span]:
        """Open a span, yield it for the caller to annotate, and export on close.

        A valid ``parent`` continues its trace (same trace id, new span id); any
        other parent starts a fresh root trace. If the body raises, the span is
        marked error with an ``exception`` event and re-raised, so the failure is
        still recorded. The caller may set status/attributes on the yielded span.
        """
        if parent is not None and parent.is_valid():
            trace_id = parent.trace_id
            parent_span_id: str | None = parent.span_id
            flags = parent.trace_flags
        else:
            trace_id = self.new_trace_id()
            parent_span_id = None
            flags = 1
        span = Span(
            name=name,
            context=SpanContext(trace_id, self.new_span_id(), flags),
            parent_span_id=parent_span_id,
            kind=kind,
            start_unix_nano=self._clock(),
            attributes=dict(attributes or {}),
        )
        try:
            yield span
        except Exception as exc:
            span.set_status(STATUS_ERROR, f"{type(exc).__name__}: {exc}")
            span.add_event(
                "exception",
                self._clock(),
                **{"exception.type": type(exc).__name__, "exception.message": str(exc)},
            )
            raise
        finally:
            if span.status_code == STATUS_UNSET:
                span.set_status(STATUS_OK)
            span.end_unix_nano = self._clock()
            self._exporter.export([span])
