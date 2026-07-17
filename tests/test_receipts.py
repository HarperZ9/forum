"""The portable submit receipt must not read MATCH over an answer the external
verifier refuted. The verification block distinguishes ledger-integrity (the
hash chain re-derives) from answer-acceptance (an external check passed)."""
from __future__ import annotations

from forum.ledger import InMemoryStorage, Ledger
from forum.receipts import submit_receipt


def _counter_ledger():
    counter = {"t": 0.0}

    def clock():
        counter["t"] += 1.0
        return counter["t"]

    return Ledger(InMemoryStorage(), clock=clock)


class _Exec:
    model_id = "m"


def _run(verifier_ok):
    led = _counter_ledger()
    led.append(actor="client", kind="request", payload={"text": "sort a list"})
    led.append(actor="worker", kind="result", payload={"answer": "sorted", "model": "m"})
    led.append(actor="verifier", kind="verification",
               payload={"ok": verifier_ok, "detail": "", "source": "s"})
    return submit_receipt(led, before_seq=0, request="sort a list",
                          answer="sorted", executor=_Exec())


def test_a_refuted_answer_does_not_read_match():
    r = _run(verifier_ok=False)
    assert r["ledger"]["verified"] is True          # the chain still re-derives
    assert r["verification"]["ledger_deep_verified"] is True
    assert r["verification"]["answer_verified"] is False
    assert r["verification"]["verdict"] != "MATCH"   # the refutation is not laundered


def test_a_verified_answer_reads_match():
    r = _run(verifier_ok=True)
    assert r["verification"]["answer_verified"] is True
    assert r["verification"]["verdict"] == "MATCH"


def test_no_verification_surfaces_the_honest_null():
    # forum stands alone by design (the default verifier abstains): the verdict
    # stays the ledger-scoped MATCH, but answer_verified is None so a reader
    # sees that no external check ran; the null is surfaced, never omitted.
    led = _counter_ledger()
    led.append(actor="client", kind="request", payload={"text": "q"})
    led.append(actor="worker", kind="result", payload={"answer": "a", "model": "m"})
    r = submit_receipt(led, before_seq=0, request="q", answer="a", executor=_Exec())
    assert r["verification"]["answer_verified"] is None   # nobody checked
    assert r["verification"]["ledger_deep_verified"] is True
