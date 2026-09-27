from __future__ import annotations

import time
from dataclasses import dataclass

from forum.gate_state import (
    DECISION_KINDS,
    GateContent,
    decision_entry,
    gate_edits,
    gate_resolution,
    matches,
    pending_gates,
    shows,
)
from forum.ledger import Ledger, LedgerEntry

__all__ = [
    "GateContent",
    "GateEditRefused",
    "GateNotFound",
    "GatePolicy",
    "decision_entry",
    "expire_gate",
    "gate_edits",
    "gate_resolution",
    "pending_deadline",
    "pending_gates",
    "resolve_gate",
]

_RESOLVE_KINDS = frozenset(DECISION_KINDS)

# The on-expiry decisions a deadline policy may choose, and the gate_expired
# payload ``decision`` each writes. reject is the safe default: an unattended
# gate that lapses does NOT silently ship its wave unless the operator opted in.
_EXPIRY_DECISIONS = {"approve": "approved", "reject": "rejected"}


@dataclass(frozen=True, slots=True)
class GatePolicy:
    """Which waves pause for human approval, and the question the operator answers.

    A gate fires at a wave boundary: before dispatching wave ``i`` (i in
    ``gated_waves``), dispatch reads the ledger for a resolution keyed to
    (run_seq, wave=i) and to the wave's content. ``question``, the wave's task
    ids and their instructions are copied into the gate_pending entry so the
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


class GateNotFound(LookupError):
    """No gate_pending exists for this (run_seq, wave), so a decision has nothing to resolve.

    Raised by ``resolve_gate(..., require_pending=True)`` before anything is
    written. ``code`` is the closed error slug the CLI, HTTP and MCP surfaces report.
    """

    code = "NOT_FOUND"


class GateEditRefused(ValueError):
    """An edit names a task the gate did not show, so nothing is written.

    A gate covers one wave; an edit may rewrite only the tasks of that wave.
    """

    code = "INVALID_ARGUMENT"


def pending_deadline(
    ledger: Ledger, run_seq: object, wave: object, *, content: GateContent | None = None
) -> float | None:
    """Absolute deadline recorded on this gate's gate_pending, or None.

    Pure ledger read. None when the gate carries no deadline (an unbounded gate)
    or has no gate_pending yet. The latest gate_pending wins (a re-raise would
    supersede), mirroring the resolution scans.
    """
    deadline: float | None = None
    for entry in ledger.query(kind="gate_pending"):
        body = ledger.get_payload(entry.payload_hash)
        if matches(body, run_seq, wave) and shows(body, content):
            raw = body.get("deadline")
            deadline = float(raw) if isinstance(raw, (int, float)) else None
    return deadline


def expire_gate(
    ledger: Ledger,
    run_seq: object,
    wave: object,
    *,
    clock=time.time,
    content: GateContent | None = None,
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
    if gate_resolution(ledger, run_seq, wave, content=content) != "pending":
        return None
    deadline = pending_deadline(ledger, run_seq, wave, content=content)
    if deadline is None or float(clock()) < deadline:
        return None
    pend: LedgerEntry | None = None
    on_expiry = "reject"
    for entry in ledger.query(kind="gate_pending"):
        body = ledger.get_payload(entry.payload_hash)
        if matches(body, run_seq, wave) and shows(body, content):
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
    require_pending: bool = False,
    approver_source: str | None = None,
    asserted_approver: str | None = None,
) -> LedgerEntry:
    """Append a decision for a pending gate and sync the ledger.

    ``kind`` is one of 'gate_approved', 'gate_edited', 'gate_rejected'. The entry
    is chained to the gate_pending it resolves (found by (run_seq, wave)). An edit
    naming a task outside that gate's wave raises GateEditRefused and writes nothing.

    With ``require_pending=True``, which every CLI, HTTP and MCP path uses, a
    (run_seq, wave) with no gate_pending raises GateNotFound and nothing is
    written. The default keeps the 1.14 library contract: with no gate_pending the
    entry chains to run_seq so it is still witnessed, but it is inert, because
    gate_resolution counts only decisions chained to a raised gate.

    ``approver_source`` records how the approver was established ('asserted' when
    the caller named it, 'authenticated' when a verified token did), and
    ``asserted_approver`` keeps a name the caller gave that differs from the
    authenticated one. Both are omitted from the payload when None.
    Writes are synchronous (append + sync); the pending lookup is a pure query.
    """
    if kind not in _RESOLVE_KINDS:
        raise ValueError(f"unknown gate decision kind: {kind!r}")
    parent: int | None = None
    shown: list[str] = []
    for entry in ledger.query(kind="gate_pending"):
        body = ledger.get_payload(entry.payload_hash)
        if matches(body, run_seq, wave):
            parent = entry.seq
            shown = [str(t) for t in body.get("tasks") or []]
    if parent is None:
        if require_pending:
            raise GateNotFound(f"no gate is pending for run_seq {run_seq} wave {wave}")
        parent = run_seq
    elif kind == "gate_edited":
        outside = sorted(set(edits or {}) - set(shown))
        if outside:
            raise GateEditRefused(
                f"an edit may rewrite only the tasks this gate shows; not in wave {wave}: {outside}"
            )
    payload: dict[str, object] = {"run_seq": run_seq, "wave": wave, "approver": approver}
    if approver_source is not None:
        payload["approver_source"] = approver_source
    if asserted_approver is not None:
        payload["asserted_approver"] = asserted_approver
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
