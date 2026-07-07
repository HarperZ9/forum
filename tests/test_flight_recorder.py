"""Falsifiers for the flight recorder — any framework's trace -> verifiable ledger.

Load-bearing: (1) a trace folds into a ledger that VERIFIES (hash chain +
payloads); (2) tampering an entry breaks verification (the recording refutes its
own tampering); (3) causal parents are resolved by id -> seq; (4) each supported
format normalizes, and a malformed event fails LOUD (never silently dropped).
"""
from __future__ import annotations

from forum.flight_recorder import (
    TraceParseError,
    import_trace,
    normalize_trace,
)
from forum.ledger import GENESIS, InMemoryStorage, Ledger, merkle_root

import pytest

GENERIC = [
    {"actor": "planner", "kind": "plan", "id": "a", "payload": {"goal": "x"}},
    {"actor": "worker", "kind": "act", "id": "b", "parent": "a", "payload": {"step": 1}},
    {"actor": "worker", "kind": "act", "id": "c", "parent": "b", "payload": {"step": 2}},
]


def test_trace_folds_into_a_verifying_ledger():
    rec = import_trace(GENERIC, "generic")
    assert rec["entries"] == 3
    assert rec["verified"] is True
    assert rec["merkle_root"] != GENESIS
    # deterministic: same trace -> same root
    assert import_trace(GENERIC, "generic")["merkle_root"] == rec["merkle_root"]


def test_causal_parents_resolved_by_id():
    rec = import_trace(GENERIC, "generic")
    seqs = {e["seq"]: e for e in rec["ledger"]}
    b = next(e for e in rec["ledger"] if e["actor"] == "worker" and e["kind"] == "act"
             and e["causal_parent"] == 0)
    assert b["seq"] == 1                          # b's parent is a (seq 0)
    c = rec["ledger"][2]
    assert c["causal_parent"] == 1                # c's parent is b (seq 1)


def test_tampering_breaks_verification():
    # rebuild the same ledger, tamper one stored entry, and verify() must fail
    counter = {"t": 0.0}
    led = Ledger(InMemoryStorage(), clock=lambda: (counter.__setitem__("t", counter["t"] + 1), counter["t"])[1])
    for ev in GENERIC:
        led.append(actor=ev["actor"], kind=ev["kind"], payload=ev["payload"])
    assert led.verify(deep=True)
    # corrupt a payload body in storage -> deep verify fails
    entries = led._s.all()
    bad_hash = "0" * 64
    object.__setattr__(entries[0], "payload_hash", bad_hash)
    assert led.verify(deep=True) is False


def test_langsmith_and_otel_and_agentops_normalize():
    ls = normalize_trace([{"name": "chain", "run_type": "chain", "id": "1"},
                          {"name": "llm", "run_type": "llm", "id": "2", "parent_run_id": "1"}],
                         "langsmith")
    assert ls[0]["kind"] == "chain" and ls[1]["parent_id"] == "1"
    ot = normalize_trace([{"name": "root", "span_id": "s1"},
                          {"name": "child", "span_id": "s2", "parent_span_id": "s1"}], "otel")
    assert ot[1]["parent_id"] == "s1"
    ao = normalize_trace([{"event_type": "action", "id": "e1"}], "agentops")
    assert ao[0]["kind"] == "action"


def test_langsmith_trace_imports_and_verifies():
    trace = [
        {"name": "agent", "run_type": "chain", "id": "r1", "inputs": {"q": "hi"}},
        {"name": "search", "run_type": "tool", "id": "r2", "parent_run_id": "r1"},
        {"name": "llm", "run_type": "llm", "id": "r3", "parent_run_id": "r1"},
    ]
    rec = import_trace(trace, "langsmith")
    assert rec["verified"] and rec["entries"] == 3
    assert rec["dangling_parents"] == 0


def test_unknown_parent_is_a_root_not_a_guess():
    rec = import_trace([{"actor": "w", "kind": "act", "id": "b", "parent": "ghost",
                         "payload": {}}], "generic")
    assert rec["ledger"][0]["causal_parent"] is None
    assert rec["dangling_parents"] == 1           # counted, not hidden


def test_malformed_events_fail_loud():
    with pytest.raises(TraceParseError, match="non-empty list"):
        import_trace([], "generic")
    with pytest.raises(TraceParseError, match="unknown format"):
        import_trace([{"actor": "a", "kind": "k"}], "nope")
    with pytest.raises(TraceParseError):          # generic needs actor+kind
        import_trace([{"foo": "bar"}], "generic")
    with pytest.raises(TraceParseError, match="not an object"):
        import_trace([42], "generic")


def test_cli_import_trace(tmp_path, capsys):
    import json
    from types import SimpleNamespace

    from forum.cli import _cmd_import_trace

    f = tmp_path / "trace.json"
    f.write_text(json.dumps(GENERIC), encoding="utf-8")
    assert _cmd_import_trace(SimpleNamespace(trace=str(f), format="generic")) == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["schema"] == "forum.flight-recorder/1" and rec["verified"]
