from __future__ import annotations

import time
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

# The on-expiry decisions a deadline policy may choose, and the gate_expired
# payload ``decision`` each writes. reject is the safe default: an unattended
# gate that lapses does NOT silently ship its wave unless the operator opted in.
_EXPIRY_DECISIONS = {"approve": "approved", "reject": "rejected"}


@dataclass(frozen=True, slots=True)
class GatePolicy:
    """Which waves pause for human approval, and the question the operator answers.

    A gate fires at a wave boundary: before dispatching wave ``i`` (i in
    ``gated_waves``), dispatch reads the ledger for a resolution keyed to
    (run_seq, wave=i). ``question`` is copied into the gate_pending entry so the
    operator sees what they are approving.

    ``deadline_seconds`` (optional) makes the gate durable-but-bounded: the
    gate_pending records an absolute ``deadline`` (its own witnessed ts plus this
    many seconds). If a resume re-reaches the boundary after the deadline with no
    operator decision, dispatch appends a witnessed ``gate_expired`` entry that
    auto-resolves the gate to ``on_expiry`` ('approve' or 'reject', default
    'reject' so a lapsed gate never silently ships its wave). The deadline is
    evaluated only on resume; it is not a background timer, so nothing runs
    behind the operator's back between resumes.
    """

    gated_waves: frozenset[int]
    question: str = "Approve this wave before it runs?"
    deadline_seconds: float | None = None
    on_expiry: str = "reject"

    def __post_init__(self) -> None:
        if self.deadline_seconds is not None and self.deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be positive when set")
        if self.on_expiry not in _EXPIRY_DECISIONS:
            raise ValueError(
                f"on_expiry must be 'approve' or 'reject', got {self.on_expiry!r}"
            )


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
    # A gate_expired is a witnessed auto-decision (deadline lapsed with no
    # operator action). It competes on the same highest-seq-wins rule, so an
    # operator decision recorded before OR after expiry still resolves correctly:
    # the latest witnessed decision is authoritative.
    for entry in ledger.query(kind="gate_expired"):
        body = ledger.get_payload(entry.payload_hash)
        if _matches(body, run_seq, wave):
            if best_seq is None or entry.seq > best_seq:
                best_seq = entry.seq
                resolution = str(body.get("decision") or "rejected")
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


def pending_deadline(ledger: Ledger, run_seq: object, wave: object) -> float | None:
    """Absolute deadline recorded on this gate's gate_pending, or None.

    Pure ledger read. None when the gate carries no deadline (an unbounded gate)
    or has no gate_pending yet. The latest gate_pending wins (a re-raise would
    supersede), mirroring the resolution scans.
    """
    deadline: float | None = None
    for entry in ledger.query(kind="gate_pending"):
        body = ledger.get_payload(entry.payload_hash)
        if _matches(body, run_seq, wave):
            raw = body.get("deadline")
            deadline = float(raw) if isinstance(raw, (int, float)) else None
    return deadline


def expire_gate(
    ledger: Ledger,
    run_seq: object,
    wave: object,
    *,
    clock=time.time,
) -> str | None:
    """Auto-resolve a still-pending gate whose deadline has lapsed; else no-op.

    Returns the resolution the run should now act on ('approved' | 'rejected')
    when this call appends a witnessed ``gate_expired``, otherwise None. Idempotent
    and safe to call at the wave boundary: it acts only when the gate is genuinely
    'pending' (no operator decision, no prior expiry) AND a recorded deadline has
    passed under ``clock``. The gate_expired entry is hash-chained to the
    gate_pending it resolves, carries the ``decision`` (from the pending's
    ``on_expiry``), and is synced like every other gate write, so the resumed run
    re-verifies. Unbounded gates (no deadline) always return None: they stay
    pending until the operator acts.

    INVARIANT: no await. Called inside the wave loop under cooperative
    scheduling; the read + append window must not yield (see Ledger.append).
    """
    if gate_resolution(ledger, run_seq, wave) != "pending":
        return None
    deadline = pending_deadline(ledger, run_seq, wave)
    if deadline is None or float(clock()) < deadline:
        return None
    pend: LedgerEntry | None = None
    on_expiry = "reject"
    for entry in ledger.query(kind="gate_pending"):
        body = ledger.get_payload(entry.payload_hash)
        if _matches(body, run_seq, wave):
            pend = entry
            raw = body.get("on_expiry")
            if raw in _EXPIRY_DECISIONS:
                on_expiry = str(raw)
    if pend is None:
        # Unreachable in practice: a 'pending' resolution and a recorded deadline
        # both require a matched gate_pending. Guard so the causal_parent is always
        # a concrete seq (a witnessed entry is never left unchained).
        return None
    decision = _EXPIRY_DECISIONS[on_expiry]
    ledger.append(
        actor="dispatch",
        kind="gate_expired",
        payload={
            "run_seq": run_seq,
            "wave": wave,
            "decision": decision,
            "on_expiry": on_expiry,
            "deadline": deadline,
        },
        causal_parent=pend.seq,
    )
    ledger.sync()
    return decision


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
