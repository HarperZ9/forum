import pytest

from forum.lane_gaps import (
    RouteOutcome,
    VocabularyGap,
    derive_vocabulary_gap,
    route_outcomes,
    witness_vocabulary_gap,
)
from forum.lanes import DOMAIN_LANES
from forum.ledger import InMemoryStorage, Ledger


def _ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _route(ledger, decided, confidence):
    return ledger.append(
        actor="router",
        kind="route",
        payload={"task": "sync the source mirrors", "decided": decided, "confidence": confidence},
    )


def test_gap_derives_from_consecutive_escalations():
    # the 0143 shape: five passes escalated with no decided lane,
    # confidence never above 0.154
    confidences = [0.0, 0.05, 0.1, 0.12, 0.154]
    outcomes = tuple(
        RouteOutcome(seq=i, decided=None, confidence=c) for i, c in enumerate(confidences)
    )
    gap = derive_vocabulary_gap(outcomes, domain_signal="source-federation")
    assert gap == VocabularyGap(
        domain_signal="source-federation",
        consecutive_escalations=5,
        confidence_ceiling=0.154,
        first_seq=0,
        last_seq=4,
    )


def test_gap_below_threshold_must_not_fire():
    # negative fixture: two escalations under the default threshold of three
    outcomes = (
        RouteOutcome(seq=0, decided=None, confidence=0.1),
        RouteOutcome(seq=1, decided=None, confidence=0.2),
    )
    assert derive_vocabulary_gap(outcomes, domain_signal="source-federation") is None


def test_decided_route_breaks_the_run():
    # a decided route resets the streak; only the trailing unresolved run counts
    outcomes = (
        RouteOutcome(seq=0, decided=None, confidence=0.1),
        RouteOutcome(seq=1, decided=None, confidence=0.1),
        RouteOutcome(seq=2, decided="backend", confidence=0.9),
        RouteOutcome(seq=3, decided=None, confidence=0.1),
        RouteOutcome(seq=4, decided=None, confidence=0.1),
    )
    assert derive_vocabulary_gap(outcomes, domain_signal="source-federation") is None


def test_witnessed_gap_lands_in_the_ledger():
    ledger = _ledger()
    for c in (0.0, 0.02, 0.154):
        _route(ledger, None, c)
    gap = witness_vocabulary_gap(ledger, domain_signal="source-federation")
    assert gap is not None
    assert gap.consecutive_escalations == 3
    assert gap.confidence_ceiling == 0.154
    entries = ledger.query(kind="vocabulary_gap")
    assert len(entries) == 1
    body = ledger.get_payload(entries[0].payload_hash)
    assert body == {
        "domain_signal": "source-federation",
        "consecutive_escalations": 3,
        "confidence_ceiling": 0.154,
        "first_seq": 0,
        "last_seq": 2,
    }
    # the receipt chains to the last escalation it summarizes
    assert entries[0].causal_parent == gap.last_seq
    assert ledger.verify(deep=True) is True


def test_below_threshold_witnesses_nothing():
    # negative fixture at the ledger level: too few escalations, no entry
    ledger = _ledger()
    for c in (0.0, 0.1):
        _route(ledger, None, c)
    before = ledger.count()
    assert witness_vocabulary_gap(ledger, domain_signal="source-federation") is None
    assert ledger.count() == before
    assert ledger.query(kind="vocabulary_gap") == []


def test_gap_receipt_creates_no_lane():
    # the receipt is a signal for the operator; the vocabulary stays closed
    outcomes = tuple(RouteOutcome(seq=i, decided=None, confidence=0.0) for i in range(3))
    gap = derive_vocabulary_gap(outcomes, domain_signal="unmapped-domain")
    assert gap is not None
    assert "unmapped-domain" not in DOMAIN_LANES


def test_min_escalations_must_be_at_least_one():
    with pytest.raises(ValueError):
        derive_vocabulary_gap((), domain_signal="x", min_escalations=0)


def test_route_outcomes_reads_witnessed_routes():
    ledger = _ledger()
    _route(ledger, "backend", 0.8)
    _route(ledger, None, 0.05)
    outcomes = route_outcomes(ledger)
    assert outcomes == (
        RouteOutcome(seq=0, decided="backend", confidence=0.8),
        RouteOutcome(seq=1, decided=None, confidence=0.05),
    )
