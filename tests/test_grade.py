"""Falsifiers for grade.py — the outcome grade must be able to FAIL, and a
producer must never be able to author its own passing grade.

Load-bearing: (1) flipping a passing check to failing flips the grade (can-fail);
(2) a check authored by the producing actor is not independent -> UNVERIFIABLE,
never PASS; (3) a run with zero checks is UNVERIFIABLE, so integrity is not
laundered into success; (4) the grade is deterministic under an injected clock.
"""
from __future__ import annotations

from forum.grade import grade_ledger
from forum.ledger import InMemoryStorage, Ledger


def _ledger():
    # deterministic clock so ts is reproducible
    counter = {"t": 0.0}

    def clock():
        counter["t"] += 1.0
        return counter["t"]

    return Ledger(InMemoryStorage(), clock=clock)


def test_flipped_verdict_flips_grade():
    # a producer result plus two independent passing verdicts -> PASS reward 1.0
    led = _ledger()
    led.append(actor="worker", kind="result", payload={"id": "T1", "output": "x", "ok": True})
    led.append(actor="validator", kind="verdict", payload={"id": "T1", "ok": True, "score": 1.0})
    led.append(actor="verifier", kind="verification", payload={"ok": True, "detail": "", "source": "s"})
    g = grade_ledger(led, min_checks=2)
    assert g["label"] == "PASS", g
    assert g["reward"] == 1.0

    # rebuild flipping the verdict ok -> reward < 1.0, label FAIL (the grade CAN fail)
    led2 = _ledger()
    led2.append(actor="worker", kind="result", payload={"id": "T1", "output": "x", "ok": True})
    led2.append(actor="validator", kind="verdict", payload={"id": "T1", "ok": False, "score": 0.0})
    led2.append(actor="verifier", kind="verification", payload={"ok": True, "detail": "", "source": "s"})
    g2 = grade_ledger(led2, min_checks=2)
    assert g2["label"] == "FAIL", g2
    assert g2["reward"] < 1.0
    assert g2["refuted"] == 1


def test_self_check_is_unverifiable():
    # the only check is authored by the producing actor -> not independent -> UNVERIFIABLE
    led = _ledger()
    led.append(actor="worker", kind="result", payload={"id": "T1", "output": "x", "ok": True})
    led.append(actor="worker", kind="verdict", payload={"id": "T1", "ok": True, "score": 1.0})
    g = grade_ledger(led)
    assert g["label"] == "UNVERIFIABLE", g
    assert g["checks"] == 0


def test_zero_checks_is_unverifiable_not_pass():
    # integrity without a grade must never read as success
    led = _ledger()
    led.append(actor="worker", kind="result", payload={"id": "T1", "output": "x", "ok": True})
    led.append(actor="synthesizer", kind="result", payload={"answer": "done"})
    g = grade_ledger(led)
    assert g["label"] == "UNVERIFIABLE"
    assert g["reward"] == 0.0


def test_none_ok_verification_is_non_informative():
    # a verifier that failed to run (ok=None) is excluded, not counted as pass or fail
    led = _ledger()
    led.append(actor="worker", kind="result", payload={"id": "T1", "output": "x", "ok": True})
    led.append(actor="verifier", kind="verification", payload={"ok": None, "detail": "verifier crashed", "source": ""})
    led.append(actor="validator", kind="verdict", payload={"id": "T1", "ok": True, "score": 1.0})
    g = grade_ledger(led, min_checks=1)
    assert g["checks"] == 1  # only the verdict counts
    assert g["label"] == "PASS"


def test_below_min_checks_is_not_pass():
    led = _ledger()
    led.append(actor="worker", kind="result", payload={"id": "T1", "output": "x", "ok": True})
    led.append(actor="validator", kind="verdict", payload={"id": "T1", "ok": True, "score": 1.0})
    g = grade_ledger(led, min_checks=2)
    assert g["checks"] == 1
    assert g["label"] == "FAIL"  # one passing check, but min_checks=2 not met


def test_grade_is_deterministic():
    def build():
        led = _ledger()
        led.append(actor="worker", kind="result", payload={"id": "T1", "output": "x", "ok": True})
        led.append(actor="validator", kind="verdict", payload={"id": "T1", "ok": True, "score": 1.0})
        led.append(actor="verifier", kind="verification", payload={"ok": True, "detail": "", "source": "s"})
        return grade_ledger(led)

    assert build() == build()
