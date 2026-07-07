"""Falsifiers for gradable_export.py — the exported datum must carry a grade
that can fail, must not launder integrity into success, must be deterministic,
and must expose everything needed to re-derive the witness off-forum.

The pinned witness vector (test_pinned_witness_vector) fixes a known ledger's
merkle_root as a constant. The local-model consumer pins the SAME constant; if
either side's hash recipe drifts, one of the two vector tests fails loudly
(two independent implementations must agree, like emet's frozen vectors).
"""
from __future__ import annotations

import json

from forum.gradable_export import (
    _row_hash,
    gradable_record,
    write_gradable_jsonl,
)
from forum.ledger import GENESIS, InMemoryStorage, Ledger

# The pinned cross-side vector. A ledger of exactly these three appends under the
# counter clock below has this merkle_root. The local-model intake test pins the
# identical value; a drift in either hash recipe breaks one of them.
PINNED_MERKLE_ROOT = "b79c96da02ece2a7ce60f75ff9611c7acfa30ea4d028015604e438bf7cfda1dc"


def _counter_ledger():
    counter = {"t": 0.0}

    def clock():
        counter["t"] += 1.0
        return counter["t"]

    return Ledger(InMemoryStorage(), clock=clock)


def _graded_run():
    led = _counter_ledger()
    led.append(actor="client", kind="request", payload={"text": "sort a list"})
    led.append(actor="planner", kind="plan", payload={"tasks": ["T1"]})
    led.append(actor="worker", kind="result", payload={"id": "T1", "output": "def f(): ...", "ok": True, "model": "m"})
    led.append(actor="validator", kind="verdict", payload={"id": "T1", "ok": True, "score": 1.0})
    led.append(actor="verifier", kind="verification", payload={"ok": True, "detail": "", "source": "s"})
    led.append(actor="synthesizer", kind="result", payload={"answer": "sorted"})
    return led


def test_graded_run_exports_pass_record():
    row = gradable_record(_graded_run())
    assert row["schema"] == "forum.gradable-trajectory/1"
    assert row["prompt"] == "sort a list"
    assert row["trajectory"]["answer"] == "sorted"
    assert row["grade"]["label"] == "PASS"
    assert row["grade"]["reward"] == 1.0
    assert row["oracle"]["merkle_root"] != GENESIS
    assert row["oracle"]["verified"] is True
    assert row["_"] if False else _row_hash(row) == row["row_hash"]  # seal is self-consistent


def test_unchecked_run_is_unverifiable():
    # a run with a producer and a final answer but ZERO independent checks:
    # integrity verifies, but the grade must be UNVERIFIABLE, never PASS.
    led = _counter_ledger()
    led.append(actor="client", kind="request", payload={"text": "do a thing"})
    led.append(actor="worker", kind="result", payload={"id": "T1", "output": "x", "ok": True})
    led.append(actor="synthesizer", kind="result", payload={"answer": "done"})
    row = gradable_record(led)
    assert row["oracle"]["verified"] is True          # integrity holds
    assert row["grade"]["label"] == "UNVERIFIABLE"    # but it is NOT graded PASS
    assert "witnessed" not in row                     # forum never stamps the witness


def test_export_is_deterministic():
    a = gradable_record(_graded_run())
    b = gradable_record(_graded_run())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert a["row_hash"] == b["row_hash"]
    assert a["oracle"]["merkle_root"] == b["oracle"]["merkle_root"]


def test_grade_inputs_expose_reward_derivation():
    row = gradable_record(_graded_run())
    inputs = row["oracle"]["grade_inputs"]
    assert all("actor" in i and "ok" in i and "kind" in i for i in inputs)
    passed = sum(1 for i in inputs if i["ok"])
    total = len(inputs)
    assert round(passed / total, 6) == row["grade"]["reward"]


def test_write_jsonl_roundtrips(tmp_path):
    row = gradable_record(_graded_run())
    out = tmp_path / "data.jsonl"
    n = write_gradable_jsonl([row], out)
    assert n == 1
    loaded = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert loaded[0]["row_hash"] == row["row_hash"]


def test_pinned_witness_vector():
    # freeze the known ledger's merkle_root so the cross-side recipe can't drift
    root = gradable_record(_graded_run())["oracle"]["merkle_root"]
    if PINNED_MERKLE_ROOT != "PLACEHOLDER":
        assert root == PINNED_MERKLE_ROOT, (
            f"merkle recipe drifted: {root} != pinned {PINNED_MERKLE_ROOT}")
    # else: first run — capture the value below and pin it on both sides
    assert len(root) == 64 and root != GENESIS
