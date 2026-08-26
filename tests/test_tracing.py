import itertools

import pytest

from forum.tracing import (
    KIND_SERVER,
    STATUS_ERROR,
    STATUS_OK,
    InMemorySpanExporter,
    SpanContext,
    Tracer,
    format_traceparent,
    parse_traceparent,
)


def _seq_ids():
    """A deterministic id source: n bytes of an incrementing counter."""
    counter = itertools.count(1)
    return lambda n: next(counter).to_bytes(n, "big")


def _seq_clock(start=1000):
    ticks = itertools.count(start)
    return lambda: next(ticks)


def _tracer(exporter=None):
    return Tracer(exporter, clock=_seq_clock(), id_source=_seq_ids())


# --- SpanContext + traceparent ---

def test_traceparent_round_trip():
    ctx = SpanContext("a" * 32, "b" * 16, 1)
    header = format_traceparent(ctx)
    assert header == "00-" + "a" * 32 + "-" + "b" * 16 + "-01"
    parsed = parse_traceparent(header)
    assert parsed == ctx


def test_traceparent_flags_render_two_hex_digits():
    assert format_traceparent(SpanContext("a" * 32, "b" * 16, 0)).endswith("-00")


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "00-" + "a" * 32,  # too few fields
        "ff-" + "a" * 32 + "-" + "b" * 16 + "-01",  # forbidden version
        "00-" + "0" * 32 + "-" + "b" * 16 + "-01",  # all-zero trace id
        "00-" + "a" * 32 + "-" + "0" * 16 + "-01",  # all-zero span id
        "00-" + "a" * 31 + "-" + "b" * 16 + "-01",  # short trace id
        "00-" + "g" * 32 + "-" + "b" * 16 + "-01",  # non-hex trace id
    ],
)
def test_parse_traceparent_rejects_bad_headers(header):
    assert parse_traceparent(header) is None


def test_parse_traceparent_tolerates_higher_version_suffix():
    # a future version may append fields; the leading four still parse
    header = "01-" + "a" * 32 + "-" + "b" * 16 + "-01-extra"
    ctx = parse_traceparent(header)
    assert ctx is not None and ctx.trace_id == "a" * 32


def test_span_context_validity():
    assert SpanContext("a" * 32, "b" * 16).is_valid()
    assert not SpanContext("0" * 32, "b" * 16).is_valid()
    assert not SpanContext("a" * 10, "b" * 16).is_valid()
    assert SpanContext("a" * 32, "b" * 16, 1).sampled
    assert not SpanContext("a" * 32, "b" * 16, 0).sampled


# --- Tracer ---

def test_tracer_is_deterministic_under_injection():
    a = _tracer(InMemorySpanExporter())
    b = _tracer(InMemorySpanExporter())
    with a.start_span("x"):
        pass
    with b.start_span("x"):
        pass
    sa, sb = a._exporter.spans[0], b._exporter.spans[0]
    assert sa.context == sb.context
    assert (sa.start_unix_nano, sa.end_unix_nano) == (sb.start_unix_nano, sb.end_unix_nano)


def test_root_span_gets_new_trace_and_no_parent():
    exporter = InMemorySpanExporter()
    with _tracer(exporter).start_span("root", kind=KIND_SERVER) as span:
        span.attributes["k"] = "v"
    recorded = exporter.spans[0]
    assert recorded.parent_span_id is None
    assert recorded.kind == KIND_SERVER
    assert recorded.status_code == STATUS_OK
    assert recorded.end_unix_nano > recorded.start_unix_nano
    assert recorded.attributes["k"] == "v"


def test_child_span_continues_parent_trace():
    parent = SpanContext("a" * 32, "b" * 16, 1)
    exporter = InMemorySpanExporter()
    with _tracer(exporter).start_span("child", parent=parent):
        pass
    child = exporter.spans[0]
    assert child.context.trace_id == parent.trace_id  # same trace
    assert child.parent_span_id == parent.span_id  # linked to the parent span
    assert child.context.span_id != parent.span_id  # but its own span id


def test_invalid_parent_starts_a_fresh_trace():
    bad = SpanContext("0" * 32, "b" * 16, 1)  # invalid trace id
    exporter = InMemorySpanExporter()
    with _tracer(exporter).start_span("child", parent=bad):
        pass
    span = exporter.spans[0]
    assert span.parent_span_id is None
    assert span.context.trace_id != bad.trace_id


def test_exception_marks_error_records_event_and_reraises():
    exporter = InMemorySpanExporter()
    with pytest.raises(ValueError):
        with _tracer(exporter).start_span("boom"):
            raise ValueError("nope")
    span = exporter.spans[0]  # exported despite the raise
    assert span.status_code == STATUS_ERROR
    assert "ValueError: nope" in span.status_message
    assert span.events[0].name == "exception"
    assert span.events[0].attributes["exception.type"] == "ValueError"


def test_null_exporter_is_the_default_and_records_nothing():
    tracer = _tracer()  # no exporter -> NullSpanExporter
    with tracer.start_span("x") as span:
        assert span.context.is_valid()  # still a real, valid span
