"""Pure reads of a gate's state: which decision counts, and what it decided.

A decision counts only when it is chained to a gate_pending for the same
(run_seq, wave) and written after it. Among counted decisions, one made with a
verified token outranks every decision a caller only asserted; within one
standing the latest wins. With ``content`` (the wave digest and task ids a
dispatch is about to run) only a gate that showed that content counts, so an
approval never covers tasks the person did not see. Every function here is a
pure ``ledger.query`` scan with no await, safe inside the wave loop.
"""
from __future__ import annotations

from forum.ledger import Ledger, LedgerEntry

# The decision entry kinds an operator can append to resolve a pending gate, and
# the resolution string each maps to. gate_pending on its own (no decision) reads
# as "pending": the run is blocked waiting for the operator.
DECISION_KINDS = {
    "gate_approved": "approved",
    "gate_edited": "edited",
    "gate_rejected": "rejected",
}
# How a decision's approver was established. A decision made with a verified
# token outranks every decision a caller only asserted (a CLI user, an MCP
# client, an HTTP call with auth off).
_AUTHENTICATED = "authenticated"

# What a gate showed: (wave_digest, task ids). A gate raised before 1.15.0
# recorded ids only, so it matches on ids; a newer one matches on the digest.
GateContent = tuple[str, list[str]]


def matches(body: object, run_seq: object, wave: object) -> bool:
    """True if a payload body targets this (run_seq, wave). Pure dict read, no await."""
    if not isinstance(body, dict):
        return False
    return body.get("run_seq") == run_seq and body.get("wave") == wave


def shows(body: dict, content: GateContent | None) -> bool:
    """True if this gate_pending body showed ``content`` (always, when content is None)."""
    if content is None:
        return True
    digest, task_ids = content
    recorded = body.get("wave_digest")
    if recorded is not None:
        return recorded == digest
    return list(body.get("tasks") or []) == list(task_ids)


def _pending_seqs(
    ledger: Ledger, run_seq: object, wave: object, content: GateContent | None
) -> set[int]:
    """Seqs of every gate_pending raised for this (run_seq, wave) showing ``content``."""
    seqs: set[int] = set()
    for entry in ledger.query(kind="gate_pending"):
        body = ledger.get_payload(entry.payload_hash)
        if matches(body, run_seq, wave) and shows(body, content):
            seqs.add(entry.seq)
    return seqs


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
        if matches(body, run_seq, wave):
            out.append((entry, body))
    return out


def _authoritative(
    ledger: Ledger,
    run_seq: object,
    wave: object,
    kinds: tuple[str, ...],
    content: GateContent | None,
) -> tuple[str, LedgerEntry, dict] | None:
    """The counted entry of ``kinds`` that decides this gate: highest standing, then latest.

    A decision made with a verified token outranks every asserted decision, so a
    model or a replayed request cannot reverse what an authenticated person
    decided. Among decisions of one standing the highest seq wins, so a changed
    mind (reject then approve) resolves correctly. A dispatch gate_expired stands
    with the asserted decisions.
    """
    pending = _pending_seqs(ledger, run_seq, wave, content)
    best: tuple[str, LedgerEntry, dict] | None = None
    best_key: tuple[int, int] | None = None
    for kind in kinds:
        for entry, body in _counted(ledger, kind, run_seq, wave, pending):
            standing = 1 if body.get("approver_source") == _AUTHENTICATED else 0
            key = (standing, entry.seq)
            if best_key is None or key > best_key:
                best_key, best = key, (kind, entry, body)
    return best


def gate_resolution(
    ledger: Ledger, run_seq: object, wave: object, *, content: GateContent | None = None
) -> str | None:
    """Read the ledger for this gate's state: 'approved'|'edited'|'rejected'|'pending'|None.

    None means no gate_pending has been raised for (run_seq, wave), or, with
    ``content``, none showing that content, so dispatch should raise one, whatever
    decisions name that key. Once a gate is raised, a decision entry
    (gate_approved / gate_edited / gate_rejected) or a dispatch gate_expired
    resolves it only if it is chained to that gate_pending and written after it;
    among those, an authenticated decision outranks an asserted one, then the
    latest wins. With none, the gate is 'pending'.
    """
    if not _pending_seqs(ledger, run_seq, wave, content):
        return None
    best = _authoritative(ledger, run_seq, wave, (*DECISION_KINDS, "gate_expired"), content)
    if best is None:
        return "pending"
    kind, _entry, body = best
    if kind == "gate_expired":
        return str(body.get("decision") or "rejected")
    return DECISION_KINDS[kind]


def decision_entry(
    ledger: Ledger,
    run_seq: object,
    wave: object,
    kinds: tuple[str, ...],
    *,
    content: GateContent | None = None,
) -> LedgerEntry | None:
    """The counted entry of one of ``kinds`` that decides this gate, or None."""
    best = _authoritative(ledger, run_seq, wave, kinds, content)
    return None if best is None else best[1]


def gate_edits(
    ledger: Ledger, run_seq: object, wave: object, *, content: GateContent | None = None
) -> dict[str, str]:
    """Task-id -> replacement instruction from the gate_edited that decides this gate.

    Returns {} when no counted gate_edited resolves this (run_seq, wave). The same
    ranking as gate_resolution picks the edit: an authenticated edit outranks an
    asserted one, then a re-edit supersedes. Only edits chained to the raised gate
    count.
    """
    best = _authoritative(ledger, run_seq, wave, ("gate_edited",), content)
    raw = best[2].get("edits") if best is not None else None
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def pending_gates(ledger: Ledger) -> list[dict]:
    """Unresolved gate_pending entries, newest last, with what each one asks the person to approve."""
    pending: list[dict] = []
    for entry in ledger.query(kind="gate_pending"):
        body = ledger.get_payload(entry.payload_hash)
        run_seq = body.get("run_seq")
        wave = body.get("wave")
        if gate_resolution(ledger, run_seq, wave) != "pending":
            continue
        item: dict = {
            "seq": entry.seq,
            "run_seq": run_seq,
            "wave": wave,
            "tasks": list(body.get("tasks") or []),
            "question": body.get("question", ""),
        }
        instructions = body.get("instructions")
        if isinstance(instructions, dict):
            item["instructions"] = dict(instructions)
        deadline = body.get("deadline")
        if isinstance(deadline, (int, float)):
            # A bounded gate: surface its deadline and the auto-decision that fires
            # on resume if it lapses (reject unless the operator opted in).
            item["deadline"] = float(deadline)
            item["on_expiry"] = str(body.get("on_expiry") or "reject")
        pending.append(item)
    return pending
