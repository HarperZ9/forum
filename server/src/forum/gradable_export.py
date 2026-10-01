"""gradable_export.py — export a completed run as a witnessed, gradable datum.

Forum's differentiator is a hash-chained, replayable ledger. This turns a
finished run (native, or one folded in from any framework by flight_recorder)
into one `forum.gradable-trajectory/1` row: a prompt, the trajectory, a grade
that CAN fail, and everything a consumer needs to re-derive both the integrity
and the grade OFF-forum with nothing but stdlib sha256 — no shared code, no
trust in forum.

Honesty boundary (deliberate): this row does NOT assert a top-level
`witnessed:true`. That would be forum vouching for its own verification — the
theatre this whole line exists to avoid. The row carries only
`oracle.verified` (forum's OWN deep-verify at export, labeled as such) plus the
raw re-derivation inputs (`entries`, `merkle_root`, `grade_inputs`). The
WITNESSED verdict is computed by the consumer when it re-derives; a datum earns
"witnessed" by surviving that independent re-check, never by this exporter
stamping it. See trajectory_intake on the local-model side.

Splits EXPORT out of flight_recorder.py (which only INGESTS a trace into a
ledger). Pure read over a Ledger; no clock, no network.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .grade import grade_ledger
from .ledger import Ledger, merkle_root


def _task_id(request_text: str) -> str:
    norm = " ".join((request_text or "").split()).lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _row_hash(row: dict[str, Any]) -> str:
    """Same seal recipe the flywheel's task_curator uses: sha256 over the
    sort_keys JSON of the row WITHOUT its own hash, first 16 hex. The two ends
    agree on this recipe without importing each other."""
    body = {k: v for k, v in row.items() if k != "row_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def _request_text(ledger: Ledger, override: str | None) -> str:
    if override is not None:
        return override
    for e in ledger.query(kind="request"):
        body = ledger.get_payload(e.payload_hash)
        if isinstance(body.get("text"), str):
            return body["text"]
    return ""


def _final_answer(ledger: Ledger) -> str | None:
    answer: str | None = None
    for e in ledger.query(kind="result"):
        body = ledger.get_payload(e.payload_hash)
        # a synthesized final answer carries "answer" and is not a revision echo
        if isinstance(body.get("answer"), str) and "revised_from" not in body:
            answer = body["answer"]  # keep the latest
    return answer


def _model_calls(ledger: Ledger) -> int:
    return sum(1 for e in ledger.query(kind="result")
               if "model" in ledger.get_payload(e.payload_hash))


def gradable_record(ledger: Ledger, *, request: str | None = None,
                    min_checks: int = 2) -> dict[str, Any]:
    """Build one forum.gradable-trajectory/1 row from a finished run's ledger."""
    entries = ledger.replay()
    projection = [{
        "seq": e.seq,
        "ts": round(e.ts, 6),
        "actor": e.actor,
        "kind": e.kind,
        "causal_parent": e.causal_parent,
        "payload_hash": e.payload_hash,
        "prev_hash": e.prev_hash,
        "entry_hash": e.entry_hash,
    } for e in entries]
    hashes = [e.entry_hash for e in entries]
    plans = ledger.query(kind="plan")
    plan_hash = plans[-1].payload_hash if plans else None
    grade = grade_ledger(ledger, min_checks=min_checks)
    req_text = _request_text(ledger, request)
    payload_bytes = sum(len(json.dumps(ledger.get_payload(e.payload_hash),
                                       sort_keys=True)) for e in entries)
    row: dict[str, Any] = {
        "schema": "forum.gradable-trajectory/1",
        "task_id": _task_id(req_text),
        "prompt": req_text,
        "trajectory": {
            "plan_hash": plan_hash,
            "answer": _final_answer(ledger),
            "entries": projection,
        },
        "grade": {
            "reward": grade["reward"],
            "label": grade["label"],
            "checks": grade["checks"],
            "refuted": grade["refuted"],
            "producers": grade["producers"],
            "graders": grade["graders"],
            "derivation": grade["derivation"],
        },
        "oracle": {
            "kind": "ledger-rewitness",
            "merkle_root": merkle_root(hashes),
            # forum's OWN deep-verify at export — a self-report, NOT the witness.
            # The consumer re-derives merkle_root + reward and decides MATCH/DRIFT.
            "verified": ledger.verify(deep=True),
            "grade_inputs": grade["grade_inputs"],
            # the check payload BODIES, bound to the merkle chain: each hashes to
            # a witnessed entry's payload_hash, so a consumer reads ok from the
            # body (not the free-floating grade_input) and a flipped grade cannot
            # survive. Without these the grade witnessed itself; this closes it.
            "check_payloads": [
                {"seq": gi["seq"], "payload_hash": gi["payload_hash"],
                 "body": ledger.get_payload(gi["payload_hash"])}
                for gi in grade["grade_inputs"]
            ],
            "recheck": ("recompute each entry_hash from its fields "
                        "(sha256 of seq|ts(.6f)|actor|kind|causal_parent|payload_hash|"
                        "prev_hash joined by \\x1f), fold the RFC6962 merkle "
                        "(0x00 leaf / 0x01 node, promote-odd) and compare to "
                        "merkle_root; for each check_payload confirm "
                        "canonical_hash(body)==payload_hash of a witnessed entry, "
                        "read ok from that bound body, and recompute reward from "
                        "the bound checks. Tamper any entry OR any check body -> "
                        "a hash mismatch; the grade cannot be forged apart from "
                        "the merkle-witnessed record."),
        },
        "budget": {
            "model_calls": _model_calls(ledger),
            "payload_bytes": payload_bytes,
            "entries": len(entries),
            "clock": "injected",
        },
    }
    row["row_hash"] = _row_hash(row)
    return row


def write_gradable_jsonl(records: list[dict[str, Any]], path: str | Path) -> int:
    """Append records as sealed JSONL. Returns the number written."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        for row in records:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    return len(records)
