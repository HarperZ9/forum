"""Vocabulary-gap receipts: witness repeated no-route escalations, typed.

When routing escalates again and again on the same kind of work and no lane
ever decides, the record should say so once, in a typed entry an operator can
act on, instead of silently accumulating identical escalations. This module
derives that receipt from the witnessed route entries. It never creates a
lane: widening either lane vocabulary (forum.lanes) stays a code change with
tests, and the receipt is the evidence an operator uses to decide whether to
make it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from forum.ledger import Ledger

# How many consecutive undecided routes count as a gap by default. Below this
# the record is treated as ordinary escalation noise and no receipt fires.
DEFAULT_MIN_ESCALATIONS = 3


@dataclass(frozen=True, slots=True)
class RouteOutcome:
    """One witnessed routing decision, read back from the record."""

    seq: int
    decided: str | None
    confidence: float


@dataclass(frozen=True, slots=True)
class VocabularyGap:
    """A typed receipt: routing kept escalating and no lane could take the work.

    The counts and the confidence ceiling are derived from witnessed route
    entries; the ``domain_signal`` is the name the operator gives the pattern
    (for example the recurring subject the escalated tasks share). Naming the
    signal routes nothing and creates nothing.
    """

    domain_signal: str
    consecutive_escalations: int
    confidence_ceiling: float
    first_seq: int
    last_seq: int


def route_outcomes(ledger: Ledger) -> tuple[RouteOutcome, ...]:
    """Read every witnessed ``route`` entry into a typed outcome, in seq order."""
    out: list[RouteOutcome] = []
    for entry in ledger.query(kind="route"):
        body = ledger.get_payload(entry.payload_hash)
        confidence = body.get("confidence")
        out.append(
            RouteOutcome(
                seq=entry.seq,
                decided=body.get("decided"),
                confidence=0.0 if confidence is None else float(confidence),
            )
        )
    return tuple(out)


def derive_vocabulary_gap(
    outcomes: Sequence[RouteOutcome],
    *,
    domain_signal: str,
    min_escalations: int = DEFAULT_MIN_ESCALATIONS,
) -> VocabularyGap | None:
    """Derive a gap receipt from the trailing run of undecided routes, or None.

    Pure function over route outcomes. The trailing run is what matters: a
    decided route breaks the streak, because a vocabulary gap is an unresolved
    present condition, not a memory of past escalations. Below
    ``min_escalations`` the answer is None and nothing fires; that refusal is
    load-bearing, a gap detector that cannot stay silent on thin evidence
    would not be a detector.
    """
    if min_escalations < 1:
        raise ValueError(f"min_escalations must be >= 1, got {min_escalations}")
    run: list[RouteOutcome] = []
    for outcome in outcomes:
        if outcome.decided is None:
            run.append(outcome)
        else:
            run = []
    if len(run) < min_escalations:
        return None
    return VocabularyGap(
        domain_signal=domain_signal,
        consecutive_escalations=len(run),
        confidence_ceiling=max(o.confidence for o in run),
        first_seq=run[0].seq,
        last_seq=run[-1].seq,
    )


def witness_vocabulary_gap(
    ledger: Ledger,
    *,
    domain_signal: str,
    min_escalations: int = DEFAULT_MIN_ESCALATIONS,
) -> VocabularyGap | None:
    """Derive a gap from the ledger's own route entries and witness it.

    When the trailing escalation run reaches the threshold, a
    ``vocabulary_gap`` entry lands in the ledger, chained to the last
    escalation it summarizes, and the receipt is returned. Below the threshold
    nothing is appended and None is returned. Either way no lane is created;
    the receipt is a signal for the operator.
    """
    gap = derive_vocabulary_gap(
        route_outcomes(ledger),
        domain_signal=domain_signal,
        min_escalations=min_escalations,
    )
    if gap is None:
        return None
    ledger.append(
        actor="router",
        kind="vocabulary_gap",
        payload={
            "domain_signal": gap.domain_signal,
            "consecutive_escalations": gap.consecutive_escalations,
            "confidence_ceiling": gap.confidence_ceiling,
            "first_seq": gap.first_seq,
            "last_seq": gap.last_seq,
        },
        causal_parent=gap.last_seq,
    )
    return gap
