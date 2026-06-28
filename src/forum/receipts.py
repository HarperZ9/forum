from __future__ import annotations

from typing import Any

from forum.executor import executor_id
from forum.hashing import canonical_hash
from forum.ledger import Ledger, LedgerEntry

SCHEMA = "project-telos.action-receipt/v1"


def _entry_ref(entry: LedgerEntry) -> dict[str, Any]:
    return {
        "seq": entry.seq,
        "kind": entry.kind,
        "actor": entry.actor,
        "payload_hash": entry.payload_hash,
        "entry_hash": entry.entry_hash,
    }


def _answer_entry(entries: list[LedgerEntry], ledger: Ledger, answer: str) -> LedgerEntry | None:
    for entry in reversed(entries):
        if entry.kind != "result":
            continue
        try:
            payload = ledger.get_payload(entry.payload_hash)
        except KeyError:
            continue
        if isinstance(payload, dict) and payload.get("answer") == answer:
            return entry
    return None


def submit_receipt(
    ledger: Ledger,
    *,
    before_seq: int,
    request: str,
    answer: str,
    executor: Any,
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entries = [entry for entry in ledger.replay() if entry.seq >= before_seq]
    request_entry = next((entry for entry in entries if entry.kind == "request"), entries[0] if entries else None)
    answer_entry = _answer_entry(entries, ledger, answer) or (entries[-1] if entries else None)
    verified = ledger.verify(deep=True)
    checkpoint = ledger.checkpoint()
    intent_material = {
        "tool": "forum",
        "action": "submit",
        "request": request,
        "request_seq": None if request_entry is None else request_entry.seq,
    }
    return {
        "schema": SCHEMA,
        "tool": "forum",
        "action": "submit",
        "action_intent_id": f"sha256:{canonical_hash(intent_material)}",
        "side_effect_class": ["ledger_write", "model_call"],
        "request": _entry_ref(request_entry) if request_entry is not None else None,
        "answer": _entry_ref(answer_entry) if answer_entry is not None else None,
        "ledger": {
            "entry_range": [
                None if not entries else entries[0].seq,
                None if not entries else entries[-1].seq,
            ],
            "entries": len(entries),
            "checkpoint": checkpoint,
            "verified": verified,
        },
        "model": {"id": executor_id(executor)},
        "budget": budget or {},
        "verification": {
            "verdict": "MATCH" if verified else "DRIFT",
            "ledger_deep_verified": verified,
        },
    }
