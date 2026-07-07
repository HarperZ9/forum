"""Falsifier for the one-command `forum mine` path: any framework's trace folds
into a verifiable ledger, gets graded, and is appended as a sealed
gradable-trajectory datum — in a single command, reusing the flight recorder.
"""
from __future__ import annotations

import json

from forum.cli import main


def test_mine_generic_trace_to_gradable_jsonl(tmp_path, capsys):
    # a generic trace: a producer result plus two independent checks -> gradable PASS
    trace = [
        {"actor": "client", "kind": "request", "id": "r", "payload": {"text": "add two ints"}},
        {"actor": "worker", "kind": "result", "id": "t1", "parent": "r",
         "payload": {"id": "t1", "output": "def add(a,b): return a+b", "ok": True, "model": "m"}},
        {"actor": "validator", "kind": "verdict", "id": "v", "parent": "t1",
         "payload": {"id": "t1", "ok": True, "score": 1.0}},
        {"actor": "verifier", "kind": "verification", "id": "w", "parent": "t1",
         "payload": {"ok": True, "detail": "runs", "source": "s"}},
    ]
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(trace), encoding="utf-8")
    out = tmp_path / "data.jsonl"

    rc = main(["mine", str(trace_path), "--format", "generic", "--out", str(out)])
    assert rc == 0

    rows = [json.loads(line) for line in out.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    row = rows[0]
    assert row["schema"] == "forum.gradable-trajectory/1"
    assert row["prompt"] == "add two ints"
    assert row["grade"]["label"] == "PASS"
    assert row["grade"]["reward"] == 1.0
    assert row["oracle"]["merkle_root"] and len(row["oracle"]["merkle_root"]) == 64
    # forum never stamps a top-level witnessed claim; the grade inputs are exposed
    assert "witnessed" not in row
    assert len(row["oracle"]["grade_inputs"]) == 2

    # appending a second mine grows the dataset (append semantics)
    main(["mine", str(trace_path), "--format", "generic", "--out", str(out)])
    rows2 = [line for line in out.read_text().splitlines() if line.strip()]
    assert len(rows2) == 2
