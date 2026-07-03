"""Durable gate deadlines: a bounded human-in-the-loop gate that auto-resolves.

A gate normally blocks a run forever until an operator acts. With a deadline the
gate stays durable but bounded: on a resume that re-reaches the boundary after
the recorded deadline has lapsed with no operator decision, dispatch appends a
witnessed ``gate_expired`` entry (hash-chained to the gate_pending) that resolves
the gate to the policy's ``on_expiry`` decision. The auto-decision is evaluated
only on resume, never by a background timer, so nothing runs behind the operator.

These tests assert real behaviour against the ledger (the source of truth):
- policy validation rejects bad deadlines / on_expiry values,
- a bounded gate records deadline + on_expiry on its gate_pending,
- before the deadline the gate is still 'pending' and nothing auto-runs,
- after the deadline, resume auto-rejects (default) or auto-approves (opt-in),
- a gate_expired is a witnessed decision that gate_resolution honours,
- a real operator decision still wins over expiry (highest witnessed seq),
- the resumed run's ledger re-verifies (deep, incl. payload rehash).
"""

import asyncio

import pytest

from forum.dispatch import dispatch_plan
from forum.executor import EchoExecutor
from forum.gates import (
    GatePolicy,
    expire_gate,
    gate_resolution,
    pending_deadline,
    resolve_gate,
)
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task


class Clock:
    """A settable clock so tests can jump past a gate's deadline deterministically."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def make_ledger(clock=None):
    return Ledger(InMemoryStorage(), clock=clock or Clock())


def _result_ids(ledger):
    return {
        ledger.get_payload(e.payload_hash).get("id")
        for e in ledger.query(kind="result")
    }


# --- policy validation -----------------------------------------------------

def test_policy_rejects_nonpositive_deadline():
    with pytest.raises(ValueError):
        GatePolicy(frozenset({1}), deadline_seconds=0)
    with pytest.raises(ValueError):
        GatePolicy(frozenset({1}), deadline_seconds=-5)


def test_policy_rejects_unknown_on_expiry():
    with pytest.raises(ValueError):
        GatePolicy(frozenset({1}), deadline_seconds=10, on_expiry="maybe")


def test_policy_defaults_are_backward_compatible():
    p = GatePolicy(frozenset({1}))
    assert p.deadline_seconds is None
    assert p.on_expiry == "reject"


# --- pending records the deadline ------------------------------------------

def test_bounded_gate_records_deadline_and_on_expiry():
    clock = Clock(1000.0)
    ledger = make_ledger(clock)
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    asyncio.run(
        dispatch_plan(
            plan, ledger, EchoExecutor(),
            gates=GatePolicy(frozenset({1}), "ship?", deadline_seconds=60, on_expiry="approve"),
        )
    )
    plan_seq = ledger.query(kind="plan")[0].seq
    pend = ledger.get_payload(ledger.query(kind="gate_pending")[0].payload_hash)
    assert pend["on_expiry"] == "approve"
    assert pend["deadline"] == pytest.approx(1000.0 + 60)
    # the deadline is exposed by the pure read helper too
    assert pending_deadline(ledger, plan_seq, 1) == pytest.approx(1060.0)
    # T2 stayed un-run; the gate is pending; the chain verifies
    assert "T2" not in _result_ids(ledger)
    assert gate_resolution(ledger, plan_seq, 1) == "pending"
    assert ledger.verify(deep=True) is True


def test_unbounded_gate_records_no_deadline():
    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), gates=GatePolicy(frozenset({1}))))
    plan_seq = ledger.query(kind="plan")[0].seq
    pend = ledger.get_payload(ledger.query(kind="gate_pending")[0].payload_hash)
    assert "deadline" not in pend
    assert pending_deadline(ledger, plan_seq, 1) is None


# --- expiry behaviour on resume --------------------------------------------

def test_before_deadline_resume_stays_pending():
    """CAN-IT-FAIL: if expiry fired early, T2 would run. It must not."""
    clock = Clock(1000.0)
    ledger = make_ledger(clock)
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    gates = GatePolicy(frozenset({1}), deadline_seconds=60, on_expiry="approve")
    asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), gates=gates))

    clock.now = 1000.0 + 30  # still inside the window
    asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), resume=True, gates=gates))

    plan_seq = ledger.query(kind="plan")[0].seq
    assert ledger.query(kind="gate_expired") == []
    assert gate_resolution(ledger, plan_seq, 1) == "pending"
    assert "T2" not in _result_ids(ledger)
    assert ledger.verify(deep=True) is True


def test_after_deadline_resume_auto_rejects_by_default():
    clock = Clock(1000.0)
    ledger = make_ledger(clock)
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    gates = GatePolicy(frozenset({1}), deadline_seconds=60)  # default on_expiry=reject
    asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), gates=gates))

    clock.now = 1000.0 + 120  # past the deadline
    asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), resume=True, gates=gates))

    plan_seq = ledger.query(kind="plan")[0].seq
    expired = ledger.query(kind="gate_expired")
    assert len(expired) == 1
    body = ledger.get_payload(expired[0].payload_hash)
    assert body["decision"] == "rejected"
    assert body["on_expiry"] == "reject"
    # rejection stops the wave: a gate_stopped is witnessed and T2 never runs
    stopped = ledger.query(kind="gate_stopped")
    assert len(stopped) == 1
    # the stop is causally chained to the gate_expired that caused it
    assert stopped[0].causal_parent == expired[0].seq
    assert "T2" not in _result_ids(ledger)
    assert gate_resolution(ledger, plan_seq, 1) == "rejected"
    assert ledger.verify(deep=True) is True


def test_after_deadline_resume_auto_approves_when_opted_in():
    clock = Clock(1000.0)
    ledger = make_ledger(clock)
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    gates = GatePolicy(frozenset({1}), deadline_seconds=60, on_expiry="approve")
    asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), gates=gates))

    clock.now = 1000.0 + 120
    results = asyncio.run(
        dispatch_plan(plan, ledger, EchoExecutor(), resume=True, gates=gates)
    )

    plan_seq = ledger.query(kind="plan")[0].seq
    body = ledger.get_payload(ledger.query(kind="gate_expired")[0].payload_hash)
    assert body["decision"] == "approved"
    # approval lets the gated wave run: T2 now has a witnessed result
    assert "T2" in _result_ids(ledger)
    assert results["T2"].ok is True
    assert gate_resolution(ledger, plan_seq, 1) == "approved"
    assert ledger.query(kind="gate_stopped") == []
    assert ledger.verify(deep=True) is True


def test_expiry_is_idempotent_across_repeated_resumes():
    clock = Clock(1000.0)
    ledger = make_ledger(clock)
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    gates = GatePolicy(frozenset({1}), deadline_seconds=60, on_expiry="approve")
    asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), gates=gates))

    clock.now = 1000.0 + 120
    asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), resume=True, gates=gates))
    asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), resume=True, gates=gates))

    # only ONE gate_expired despite two post-deadline resumes
    assert len(ledger.query(kind="gate_expired")) == 1
    assert ledger.verify(deep=True) is True


# --- operator decision still wins over expiry ------------------------------

def test_operator_decision_beats_a_lapsed_deadline():
    """An operator who approves before resume overrides the default auto-reject."""
    clock = Clock(1000.0)
    ledger = make_ledger(clock)
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    gates = GatePolicy(frozenset({1}), deadline_seconds=60)  # would auto-reject
    asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), gates=gates))
    plan_seq = ledger.query(kind="plan")[0].seq

    # operator approves after the deadline lapses but before the next resume
    clock.now = 1000.0 + 120
    resolve_gate(ledger, plan_seq, 1, "gate_approved", approver="op")

    results = asyncio.run(
        dispatch_plan(plan, ledger, EchoExecutor(), resume=True, gates=gates)
    )
    # no auto-expiry was written (the gate was already resolved), and T2 ran
    assert ledger.query(kind="gate_expired") == []
    assert "T2" in _result_ids(ledger)
    assert results["T2"].ok is True
    assert gate_resolution(ledger, plan_seq, 1) == "approved"
    assert ledger.verify(deep=True) is True


# --- expire_gate helper in isolation ---------------------------------------

def test_expire_gate_noop_without_deadline():
    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), gates=GatePolicy(frozenset({1}))))
    plan_seq = ledger.query(kind="plan")[0].seq
    assert expire_gate(ledger, plan_seq, 1, clock=lambda: 1e12) is None
    assert ledger.query(kind="gate_expired") == []


def test_expire_gate_returns_decision_and_chains_to_pending():
    clock = Clock(1000.0)
    ledger = make_ledger(clock)
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    asyncio.run(
        dispatch_plan(
            plan, ledger, EchoExecutor(),
            gates=GatePolicy(frozenset({1}), deadline_seconds=60, on_expiry="approve"),
        )
    )
    plan_seq = ledger.query(kind="plan")[0].seq
    pend = next(e for e in ledger.query(kind="gate_pending"))

    clock.now = 1000.0 + 61
    decision = expire_gate(ledger, plan_seq, 1, clock=clock)
    assert decision == "approved"
    exp = ledger.query(kind="gate_expired")[0]
    assert exp.causal_parent == pend.seq  # hash-chained to the pending it resolves
    assert ledger.verify(deep=True) is True
