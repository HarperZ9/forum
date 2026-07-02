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


def _context_budget_observed(entries: list[LedgerEntry], ledger: Ledger) -> dict[str, int]:
    payloads = []
    for entry in entries:
        if entry.kind != "context_budget":
            continue
        try:
            payloads.append(ledger.get_payload(entry.payload_hash))
        except KeyError:
            continue
    original = sum(int(p.get("original_tokens", 0)) for p in payloads)
    admitted = sum(int(p.get("admitted_tokens", 0)) for p in payloads)
    return {
        "checks": len(payloads),
        "trimmed": sum(1 for p in payloads if p.get("action") == "trimmed"),
        "omitted": sum(1 for p in payloads if p.get("action") == "omitted"),
        "tokens_original": original,
        "tokens_admitted": admitted,
        "tokens_saved": original - admitted,
    }


def _delivery_profile_observed(entries: list[LedgerEntry], ledger: Ledger) -> dict[str, int]:
    payloads = []
    for entry in entries:
        if entry.kind != "delivery_profile_check":
            continue
        try:
            payloads.append(ledger.get_payload(entry.payload_hash))
        except KeyError:
            continue
    return {
        "checks": len(payloads),
        "flagged": sum(1 for payload in payloads if payload.get("flagged")),
    }


def _latest_payload(
    entries: list[LedgerEntry], ledger: Ledger, kind: str
) -> dict[str, Any] | None:
    for entry in reversed(entries):
        if entry.kind != kind:
            continue
        try:
            payload = ledger.get_payload(entry.payload_hash)
        except KeyError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _delivery_profile_selection(
    entries: list[LedgerEntry],
    ledger: Ledger,
    requested: str | None,
    route_frame: dict[str, Any] | None,
) -> dict[str, Any]:
    check = _latest_payload(entries, ledger, "delivery_profile_check")
    selected = check.get("profile") if check else None
    if selected is None:
        source = "none"
    elif requested is not None:
        source = "explicit"
    elif route_frame is not None and selected == route_frame.get("delivery_profile"):
        source = "route_frame"
    else:
        source = "unknown"
    return {"selected": selected, "source": source}


def submit_receipt(
    ledger: Ledger,
    *,
    before_seq: int,
    request: str,
    answer: str,
    executor: Any,
    budget: dict[str, Any] | None = None,
    context_budget: dict[str, Any] | None = None,
    delivery_profile: str | None = None,
) -> dict[str, Any]:
    entries = [entry for entry in ledger.replay() if entry.seq >= before_seq]
    request_entry = next((entry for entry in entries if entry.kind == "request"), entries[0] if entries else None)
    answer_entry = _answer_entry(entries, ledger, answer) or (entries[-1] if entries else None)
    route_frame = _latest_payload(entries, ledger, "route_frame")
    delivery_selection = _delivery_profile_selection(
        entries, ledger, delivery_profile, route_frame
    )
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
        "context_budget": {
            "limits": context_budget or {},
            "observed": _context_budget_observed(entries, ledger),
        },
        "route_frame": route_frame,
        "delivery_profile": {
            "requested": delivery_profile,
            **delivery_selection,
            **_delivery_profile_observed(entries, ledger),
        },
        "verification": {
            "verdict": "MATCH" if verified else "DRIFT",
            "ledger_deep_verified": verified,
        },
    }
