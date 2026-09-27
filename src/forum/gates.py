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


class GateNotFound(LookupError):
    """No gate_pending exists for this (run_seq, wave), so a decision has nothing to resolve.

    Raised by ``resolve_gate(..., require_pending=True)`` before anything is
    written. ``code`` is the closed error slug the CLI, HTTP and MCP surfaces report.
    """

    code = "NOT_FOUND"


def _pending_seqs(ledger: Ledger, run_seq: object, wave: object) -> set[int]:
    """Seqs of every gate_pending raised for this (run_seq, wave). Pure ledger read."""
    return {
        entry.seq
        for entry in ledger.query(kind="gate_pending")
        if _matches(ledger.get_payload(entry.payload_hash), run_seq, wave)
    }


def _counted(
    ledger: Ledger, kind: str, run_seq: object, wave: object, pending: set[int]
) -> list[tuple[LedgerEntry, dict]]:
    """Entries of ``kind`` for this gate that count: chained to a raised gate_pending, after it.

    A decision (or a dispatch expiry) counts only when its causal_parent is a
    gate_pending for the same (run_seq, wave) and it was written after that
    pending entry. An entry written before the gate opened, or chained anywhere
    else, is witnessed but inert. This is what stops a decision recorded ahead of
    time from letting a gated wave run without a pause.
    """
    out: list[tuple[LedgerEntry, dict]] = []
    for entry in ledger.query(kind=kind):
        parent = entry.causal_parent
        if parent is None or parent not in pending or entry.seq <= parent:
            continue
        body = ledger.get_payload(entry.payload_hash)
        if _matches(body, run_seq, wave):
            out.append((entry, body))
    return out


def gate_resolution(
    ledger: Ledger, run_seq: object, wave: object
) -> str | None:
    """Read the ledger for this gate's state: 'approved'|'edited'|'rejected'|'pending'|None.

    Pure ``ledger.query`` scans, no await, so it is safe to call inside the wave
    loop under concurrent scheduling (it never yields). None means no gate_pending
    has been raised for (run_seq, wave), so dispatch should raise one, whatever
    decisions name that key. Once a gate is raised, a decision entry
    (gate_approved / gate_edited / gate_rejected) or a dispatch gate_expired
    resolves it only if it is chained to that gate_pending and written after it;
    among those, the latest is authoritative. With none, the gate is 'pending'.
    """
    pending = _pending_seqs(ledger, run_seq, wave)
    if not pending:
        return None
    best_seq: int | None = None
    resolution: str | None = None
    for kind, name in _DECISION_KINDS.items():
        for entry, _body in _counted(ledger, kind, run_seq, wave, pending):
            # a later decision (higher seq) supersedes an earlier one, across
            # kinds: the single highest-seq decision wins so a changed mind
            # (e.g. reject then approve) resolves correctly.
            if best_seq is None or entry.seq > best_seq:
                best_seq = entry.seq
                resolution = name
    # A gate_expired is a witnessed auto-decision (deadline lapsed with no
    # operator action). It competes on the same highest-seq-wins rule, so a
    # decision recorded before OR after expiry still resolves correctly.
    for entry, body in _counted(ledger, "gate_expired", run_seq, wave, pending):
        if best_seq is None or entry.seq > best_seq:
            best_seq = entry.seq
            resolution = str(body.get("decision") or "rejected")
    return resolution if resolution is not None else "pending"


def decision_entry(
    ledger: Ledger, run_seq: object, wave: object, kinds: tuple[str, ...]
) -> LedgerEntry | None:
    """The latest counted entry of one of ``kinds`` for this gate, or None. Pure read."""
    pending = _pending_seqs(ledger, run_seq, wave)
    found: LedgerEntry | None = None
    for kind in kinds:
        for entry, _body in _counted(ledger, kind, run_seq, wave, pending):
            if found is None or entry.seq > found.seq:
                found = entry
    return found


def gate_edits(ledger: Ledger, run_seq: object, wave: object) -> dict[str, str]:
    """Task-id -> replacement instruction from the latest counted gate_edited for this gate.

    Pure ledger read, no await. Returns {} when no counted gate_edited resolves this
    (run_seq, wave). The latest wins so a re-edit supersedes. Only edits chained to
    the raised gate count, the same rule gate_resolution applies.
    """
    edits: dict[str, str] = {}
    pending = _pending_seqs(ledger, run_seq, wave)
    for _entry, body in _counted(ledger, "gate_edited", run_seq, wave, pending):
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
    require_pending: bool = False,
    approver_source: str | None = None,
    asserted_approver: str | None = None,
) -> LedgerEntry:
    """Append a decision for a pending gate and sync the ledger.

    ``kind`` is one of 'gate_approved', 'gate_edited', 'gate_rejected'. The entry
    is chained to the gate_pending it resolves (found by (run_seq, wave)).

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
    for entry in ledger.query(kind="gate_pending"):
        if _matches(ledger.get_payload(entry.payload_hash), run_seq, wave):
            parent = entry.seq
    if parent is None:
        if require_pending:
            raise GateNotFound(f"no gate is pending for run_seq {run_seq} wave {wave}")
        parent = run_seq
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
