"""grade.py — a deterministic OUTCOME grade for a completed run's ledger.

Forum's ledger witnesses INTEGRITY: verify(deep=True) proves a trajectory is
untampered and replayable. It does NOT say whether the run SUCCEEDED. A training
loop that wants to admit a run as gradable RL data needs a success signal that
(a) can FAIL, and (b) is not authored by the same actor that produced the work.
This module derives exactly that, as a pure read over the ledger.

The rule, and why each clause is load-bearing:

  - Only kinds {verdict, verification, intent_judgment} count as CHECKS. A
    kind="result" is the producer's output, never its own grade.
  - A check counts only if it is INDEPENDENT: its actor is not one of the actors
    that produced a result in this run. A producer grading itself is discarded,
    so a run cannot manufacture a passing grade for its own output.
  - A check with ok is None (a verifier that failed to run) is non-informative:
    it neither passes nor refutes, and is excluded from the count. It cannot be
    laundered into either direction.
  - reward = passed / (passed + refuted) over the independent, informative checks.
  - label = PASS iff reward == 1.0 AND count >= min_checks AND refuted == 0;
            UNVERIFIABLE iff count == 0 (integrity is NOT a success signal);
            FAIL otherwise.

UNVERIFIABLE is the honest floor: a run nobody independently checked is not
graded PASS just because its hash chain verifies. That is the whole point.
"""
from __future__ import annotations

from typing import Any

from .ledger import Ledger

_CHECK_KINDS = ("verdict", "verification", "intent_judgment")


def _producer_actors(ledger: Ledger) -> set[str]:
    """Actors that produced a result in this run. A grade authored by any of
    these is self-graded and does not count toward an independent reward."""
    actors: set[str] = set()
    for e in ledger.query(kind="result"):
        actors.add(e.actor)
    return actors


def grade_ledger(ledger: Ledger, *, min_checks: int = 2) -> dict[str, Any]:
    """Grade a run purely from its ledger. Deterministic (no clock, no I/O)."""
    producers = _producer_actors(ledger)
    passed = 0
    refuted = 0
    inputs: list[dict[str, Any]] = []
    graders: list[str] = []
    for kind in _CHECK_KINDS:
        for e in ledger.query(kind=kind):
            if e.actor in producers:
                continue  # self-graded: not independent
            ok = ledger.get_payload(e.payload_hash).get("ok")
            if ok is None:
                continue  # verifier failed / non-informative: excluded
            if ok:
                passed += 1
            else:
                refuted += 1
            # bind each grade input to its witnessed entry (seq + payload_hash),
            # so a consumer can re-read ok from the merkle-covered body rather
            # than trusting this free-floating ok
            inputs.append({"actor": e.actor, "ok": bool(ok), "kind": kind,
                           "seq": e.seq, "payload_hash": e.payload_hash})
            graders.append(e.actor)
    count = passed + refuted
    reward = round(passed / count, 6) if count else 0.0
    if count == 0:
        label = "UNVERIFIABLE"
    elif reward == 1.0 and count >= min_checks and refuted == 0:
        label = "PASS"
    else:
        label = "FAIL"
    return {
        "reward": reward,
        "label": label,
        "checks": count,
        "refuted": refuted,
        "producers": sorted(producers),
        "graders": graders,
        "grade_inputs": inputs,
        "min_checks": min_checks,
        "derivation": ("PASS iff reward==1.0 and checks>=min_checks and refuted==0; "
                       "UNVERIFIABLE iff checks==0; else FAIL"),
    }
