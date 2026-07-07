"""flight_recorder.py — fold any framework's agent trace into a verifiable ledger.

Forum's differentiator is a hash-chained, replayable causal ledger. Every other
orchestration and observability tool (LangSmith, Langfuse, OTel, AgentOps)
records what an agent did, but the record is a mutable log you have to trust.
This is the seam that turns their trace into forum's: normalize an external
agent trace to ledger entries and append them, so ANY framework's run gains
tamper-evidence (verify), causal replay, and a Merkle root — a flight recorder
whose recording refutes its own tampering.

Supported inputs (normalized to (actor, kind, payload, causal_parent)):
  - "langsmith"  LangChain/LangSmith runs: {name, run_type, inputs, outputs,
                 id, parent_run_id}
  - "otel"       OpenTelemetry spans: {name, span_id, parent_span_id, attributes}
  - "agentops"   AgentOps events: {event_type, ..., id, parent_id}
  - "generic"    already {actor, kind, payload, parent} (parent = index or None)

FAIL LOUD: an event a mapper cannot read raises rather than silently dropping a
step — a flight recorder that quietly loses a step is worse than none. Causal
parents are resolved by id -> ledger seq; an unknown parent id is recorded as a
root (None) with the dangling id kept in the payload, never guessed.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .ledger import GENESIS, InMemoryStorage, Ledger, merkle_root


class TraceParseError(ValueError):
    """The input is not a trace we can fold faithfully into a ledger."""


def _norm_langsmith(ev: dict) -> dict:
    if "name" not in ev and "run_type" not in ev:
        raise TraceParseError("langsmith event needs 'name' or 'run_type'")
    return {"actor": str(ev.get("name") or ev.get("run_type") or "run"),
            "kind": str(ev.get("run_type") or "run"),
            "id": ev.get("id") or ev.get("run_id"),
            "parent_id": ev.get("parent_run_id"),
            "payload": ev}


def _norm_otel(ev: dict) -> dict:
    if "name" not in ev and "span_id" not in ev:
        raise TraceParseError("otel span needs 'name' or 'span_id'")
    return {"actor": str(ev.get("name") or ev.get("span_id") or "span"),
            "kind": "span",
            "id": ev.get("span_id"),
            "parent_id": ev.get("parent_span_id"),
            "payload": ev}


def _norm_agentops(ev: dict) -> dict:
    if "event_type" not in ev:
        raise TraceParseError("agentops event needs 'event_type'")
    return {"actor": str(ev.get("agent") or ev.get("event_type")),
            "kind": str(ev["event_type"]),
            "id": ev.get("id") or ev.get("event_id"),
            "parent_id": ev.get("parent_id"),
            "payload": ev}


def _norm_generic(ev: dict) -> dict:
    if "actor" not in ev or "kind" not in ev:
        raise TraceParseError("generic event needs 'actor' and 'kind'")
    return {"actor": str(ev["actor"]), "kind": str(ev["kind"]),
            "id": ev.get("id"), "parent_id": ev.get("parent"),
            "payload": ev.get("payload", ev)}


_MAPPERS = {"langsmith": _norm_langsmith, "otel": _norm_otel,
            "agentops": _norm_agentops, "generic": _norm_generic}


def normalize_trace(events: Sequence[dict], fmt: str) -> list[dict]:
    mapper = _MAPPERS.get(fmt)
    if mapper is None:
        raise TraceParseError(f"unknown format {fmt!r}; known: {', '.join(sorted(_MAPPERS))}")
    if not isinstance(events, list) or not events:
        raise TraceParseError("trace must be a non-empty list of events")
    return [mapper(ev if isinstance(ev, dict) else _bad(ev, i))
            for i, ev in enumerate(events)]


def _bad(ev: Any, i: int):
    raise TraceParseError(f"event #{i} is not an object: {type(ev).__name__}")


def import_trace(events: Sequence[dict], fmt: str = "generic",
                 *, clock=None) -> dict:
    """Fold a trace into a fresh in-memory ledger and return a witnessed record:
    the ledger entries, the verify verdict, and the Merkle root. Deterministic
    given `clock` (a counter is used if none is supplied, so ts is reproducible)."""
    norm = normalize_trace(events, fmt)
    counter = {"t": 0.0}

    def _c():
        counter["t"] += 1.0
        return counter["t"]

    ledger = Ledger(InMemoryStorage(), clock=clock or _c)
    id_to_seq: dict[Any, int] = {}
    entries = []
    dangling = 0
    for n in norm:
        parent_seq = None
        pid = n.get("parent_id")
        if pid is not None:
            parent_seq = id_to_seq.get(pid)
            if parent_seq is None:
                dangling += 1                      # unknown parent -> root, id kept
        e = ledger.append(actor=n["actor"], kind=n["kind"],
                          payload=n["payload"], causal_parent=parent_seq)
        if n.get("id") is not None:
            id_to_seq[n["id"]] = e.seq
        entries.append({"seq": e.seq, "actor": e.actor, "kind": e.kind,
                        "causal_parent": e.causal_parent, "entry_hash": e.entry_hash})
    root = merkle_root([e["entry_hash"] for e in entries]) if entries else GENESIS
    return {
        "schema": "forum.flight-recorder/1",
        "format": fmt,
        "entries": len(entries),
        "verified": ledger.verify(deep=True),
        "merkle_root": root,
        "dangling_parents": dangling,
        "ledger": entries,
        "recheck": ("re-run import_trace over the same trace and compare the "
                    "merkle_root; tamper any entry and verify() fails"),
    }
