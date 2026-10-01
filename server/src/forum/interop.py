"""Interop: forum's ledger entries as organ-bundle interchange entries.

The organ bundle is the shared spine gather, crucible, index, learn, and forum
compose on. This module maps forum's ledger entries (the witnessed causal chain)
into that entry shape, so a forum route, a gate decision, or a run-room event
can compose into the cross-tool receipt spine.

Entry shape matches the proof-surface organ-bundle contract
(entry_id, organ_id, receipt_kind, status, payload_sha256, summary, payload_ref).
gather/src/gather/interop.py is the reference implementation.
"""
from __future__ import annotations

import re

ORGAN = "forum"
SPINE_KIND = "forum-route"
STATUSES = frozenset({
    "pass", "fail", "unverified", "warn", "needs-human", "not-applicable", "unknown",
})
_HEX = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = ("entry_id", "organ_id", "receipt_kind", "status", "payload_sha256",
           "summary", "payload_ref")

# Map forum entry kinds to a spine status.
_KIND_TO_STATUS = {
    "task_completed": "pass",
    "task_failed": "fail",
    "gate_approved": "pass",
    "gate_rejected": "fail",
    "gate_edit": "warn",
    "error": "fail",
}


def _entry(entry_id: str, status: str, payload_sha256: str, summary: str, ref: str) -> dict:
    return {
        "entry_id": entry_id,
        "organ_id": ORGAN,
        "receipt_kind": SPINE_KIND,
        "status": status,
        "payload_sha256": payload_sha256,
        "summary": summary[:160],
        "payload_ref": ref,
    }


def ledger_entry(entry, *, entry_id: str = "forum-ledger-1",
                 ref: str = "forum://ledger") -> dict:
    """Map a forum LedgerEntry into an organ-bundle entry.

    The entry's entry_hash is the payload digest; the kind maps to a spine
    status; the actor and kind go into the summary.
    """
    kind = getattr(entry, "kind", "unknown")
    actor = getattr(entry, "actor", "?")
    seq = getattr(entry, "seq", 0)
    status = _KIND_TO_STATUS.get(kind, "unverified")
    summary = f"seq {seq}: {actor} {kind}"
    sha = getattr(entry, "entry_hash", "")
    return _entry(entry_id, status, sha, summary, ref)


def route_entry(decided: str, *, needs_escalation: bool = False,
                entry_id: str = "forum-route-1",
                payload_sha256: str = "",
                ref: str = "forum://route") -> dict:
    """Map a forum routing decision into an organ-bundle entry.

    A route decision carries the decided lane and whether it needs escalation.
    """
    status = "needs-human" if needs_escalation else "pass"
    summary = f"decided={decided}, escalated={needs_escalation}"
    if not payload_sha256:
        import hashlib
        payload_sha256 = hashlib.sha256(
            f"{decided}:{needs_escalation}".encode("utf-8")
        ).hexdigest()
    return _entry(entry_id, status, payload_sha256, summary, ref)


def validate_entry(entry: dict) -> bool:
    """Validate one organ-bundle entry shape. Returns True if well-formed."""
    if not isinstance(entry, dict):
        return False
    if set(entry.keys()) != set(_FIELDS):
        return False
    if entry["organ_id"] != ORGAN:
        return False
    if entry["receipt_kind"] != SPINE_KIND:
        return False
    if entry["status"] not in STATUSES:
        return False
    if not _HEX.match(entry.get("payload_sha256", "")):
        return False
    return True
