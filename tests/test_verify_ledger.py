"""Falsifiers for the vendored standalone verifier verify_ledger.py.

The verifier ships at the repo root, imports only the standard library, and never
imports forum. A stranger holding one exported forum.gradable-trajectory/1 row
re-derives its hash chain from genesis and compares to the recorded seals. These
tests build a real sealed export with forum's own producer (test-only), then run
the verifier as a subprocess from a neutral directory with a scrubbed environment
so it cannot reach the forum package on the path.

Exit contract under test: 0 MATCH, 1 DRIFT (a chain, merkle, or seal mismatch),
2 UNVERIFIABLE (artifact missing or unreadable).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from forum.gradable_export import _row_hash, gradable_record, write_gradable_jsonl
from forum.ledger import InMemoryStorage, Ledger

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFIER = REPO_ROOT / "verify_ledger.py"


def _counter_ledger() -> Ledger:
    counter = {"t": 0.0}

    def clock() -> float:
        counter["t"] += 1.0
        return counter["t"]

    return Ledger(InMemoryStorage(), clock=clock)


def _graded_run() -> Ledger:
    led = _counter_ledger()
    led.append(actor="client", kind="request", payload={"text": "sort a list"})
    led.append(actor="planner", kind="plan", payload={"tasks": ["T1"]})
    led.append(actor="worker", kind="result",
               payload={"id": "T1", "output": "def f(): ...", "ok": True, "model": "m"})
    led.append(actor="validator", kind="verdict", payload={"id": "T1", "ok": True, "score": 1.0})
    led.append(actor="verifier", kind="verification", payload={"ok": True, "detail": "", "source": "s"})
    led.append(actor="synthesizer", kind="result", payload={"answer": "sorted"})
    return led


def _write_export(tmp_path: Path) -> Path:
    row = gradable_record(_graded_run())
    out = tmp_path / "gradable.jsonl"
    write_gradable_jsonl([row], out)
    return out


def _run(path: Path) -> subprocess.CompletedProcess[str]:
    # Run the verifier as a stranger would: CLI, argv only, from a neutral cwd with
    # PYTHONPATH dropped. The authoritative zero-import guard is the source-parse
    # test below; forum may still be reachable here via an editable install, so this
    # subprocess exercises the CLI contract rather than proving the import boundary.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, str(VERIFIER), str(path)],
        cwd=str(path.parent), env=env, capture_output=True, text=True,
    )


def test_clean_export_matches(tmp_path):
    out = _write_export(tmp_path)
    res = _run(out)
    assert res.returncode == 0, res.stderr
    assert "MATCH" in res.stdout


def test_naive_tamper_drifts(tmp_path):
    out = _write_export(tmp_path)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    row["trajectory"]["entries"][2]["actor"] = "impostor"  # break a field, do not reseal
    out.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    res = _run(out)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "DRIFT" in res.stdout


def test_resealed_chain_tamper_drifts(tmp_path):
    # flip an entry field AND recompute the row seal so the seal passes: only a real
    # chain re-derivation (not a schema/seal check) can still catch this.
    out = _write_export(tmp_path)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    row["trajectory"]["entries"][2]["actor"] = "impostor"
    row["row_hash"] = _row_hash(row)
    out.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    res = _run(out)
    assert res.returncode == 1, res.stdout + res.stderr
    assert "DRIFT" in res.stdout


def test_missing_artifact_unverifiable(tmp_path):
    res = _run(tmp_path / "does-not-exist.jsonl")
    assert res.returncode == 2, res.stdout + res.stderr
    assert "UNVERIFIABLE" in res.stdout


def test_verifier_imports_only_stdlib():
    src = VERIFIER.read_text(encoding="utf-8")
    assert "import forum" not in src and "from forum" not in src
    stdlib = {"json", "hashlib", "pathlib", "sys"}
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("import "):
            assert s.split()[1].split(".")[0] in stdlib, s
        elif s.startswith("from ") and " import " in s:
            assert s.split()[1].split(".")[0] in stdlib, s
