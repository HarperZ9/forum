from __future__ import annotations

from dataclasses import dataclass

from forum.ledger import Ledger, LedgerEntry

# The decision entry kinds an operator can append to resolve a pending gate, and
# the resolution string each maps to. gate_pending on its own (no decision) reads
# as "pending": the run is blocked waiting for the operator.
_DECISION_KINDS = {
    "gate_approved": "approved",
    "gate_edited": "edited",
    "gate_rejected": "rejected",
}
_RESOLVE_KINDS = frozenset(_DECISION_KINDS)


@dataclass(frozen=True, slots=True)
class GatePolicy:
    """Which waves pause for human approval, and the question the operator answers.

    A gate fires at a wave boundary: before dispatching wave ``i`` (i in
    ``gated_waves``), dispatch reads the ledger for a resolution keyed to
    (run_seq, wave=i). ``question`` is copied into the gate_pending entry so the
    operator sees what they are approving.
    """

    gated_waves: frozenset[int]
    question: str = "Approve this wave before it runs?"


def _matches(body: object, run_seq: object, wave: object) -> bool:
    """True if a payload body targets this (run_seq, wave). Pure dict read, no await."""
    if not isinstance(body, dict):
        return False
    return body.get("run_seq") == run_seq and body.get("wave") == wave


def gate_resolution(
    ledger: Ledger, run_seq: object, wave: object
) -> str | None:
    """Read the ledger for this gate's state: 'approved'|'edited'|'rejected'|'pending'|None.

    Pure ``ledger.query`` scans, no await, so it is safe to call inside the wave
    loop under concurrent scheduling (it never yields). A decision entry
    (gate_approved / gate_edited / gate_rejected) for (run_seq, wave) wins; the
    latest decision is authoritative. With only a gate_pending and no decision,
    the gate is 'pending' (the run is blocked). With nothing, None (no gate has
    fired yet, so dispatch should raise one).
    """
    best_seq: int | None = None
    resolution: str | None = None
    for kind, name in _DECISION_KINDS.items():
        for entry in ledger.query(kind=kind):
            if _matches(ledger.get_payload(entry.payload_hash), run_seq, wave):
                # a later decision (higher seq) supersedes an earlier one,
                # across kinds: the single highest-seq decision wins so a
                # changed-mind (e.g. reject then approve) resolves correctly.
                if best_seq is None or entry.seq > best_seq:
                    best_seq = entry.seq
                    resolution = name
    if resolution is not None:
        return resolution
    for entry in ledger.query(kind="gate_pending"):
        if _matches(ledger.get_payload(entry.payload_hash), run_seq, wave):
            return "pending"
    return None


def gate_edits(ledger: Ledger, run_seq: object, wave: object) -> dict[str, str]:
    """Task-id -> replacement instruction from the latest gate_edited for this gate.

    Pure ledger read, no await. Returns {} when no gate_edited resolves this
    (run_seq, wave). The latest gate_edited wins so a re-edit supersedes.
    """
    edits: dict[str, str] = {}
    for entry in ledger.query(kind="gate_edited"):
        body = ledger.get_payload(entry.payload_hash)
        if _matches(body, run_seq, wave):
            raw = body.get("edits") or {}
            if isinstance(raw, dict):
                edits = {str(k): str(v) for k, v in raw.items()}
    return edits


def resolve_gate(
    ledger: Ledger,
    run_seq: int,
    wave: int,
    kind: str,
    *,
    approver: str,
    note: str = "",
    reason: str = "",
    edits: dict[str, str] | None = None,
) -> LedgerEntry:
    """Append an operator's decision for a pending gate and sync the ledger.

    ``kind`` is one of 'gate_approved', 'gate_edited', 'gate_rejected'. The entry
    is chained to the gate_pending it resolves (found by (run_seq, wave)); if no
    gate_pending exists it chains to run_seq so the entry is still witnessed.
    Writes are synchronous (append + sync), like the checkpoint at the wave
    boundary; the read that finds the pending seq is a pure query.
    """
    if kind not in _RESOLVE_KINDS:
        raise ValueError(f"unknown gate decision kind: {kind!r}")
    parent = run_seq
    for entry in ledger.query(kind="gate_pending"):
        if _matches(ledger.get_payload(entry.payload_hash), run_seq, wave):
            parent = entry.seq
    payload: dict[str, object] = {"run_seq": run_seq, "wave": wave, "approver": approver}
    if kind == "gate_rejected":
        payload["reason"] = reason
    elif kind == "gate_edited":
        payload["edits"] = dict(edits or {})
        payload["note"] = note
    else:  # gate_approved
        payload["note"] = note
    written = ledger.append(actor="operator", kind=kind, payload=payload, causal_parent=parent)
    ledger.sync()
    return written
