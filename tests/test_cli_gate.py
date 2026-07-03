import json

from forum.cli import main
from forum.gates import gate_edits, gate_resolution
from forum.ledger import Ledger
from forum.storage import FileStorage


def _seed_pending(directory):
    led = Ledger(FileStorage(directory))
    req = led.append(actor="client", kind="request", payload={"tasks": ["T1", "T2"]})
    plan = led.append(
        actor="dispatch", kind="plan", payload={"waves": [["T1"], ["T2"]], "edges": []},
        causal_parent=req.seq,
    )
    led.append(
        actor="dispatch", kind="gate_pending",
        payload={"run_seq": plan.seq, "wave": 1, "tasks": ["T2"], "question": "approve?", "requested_by": "dispatch"},
        causal_parent=plan.seq,
    )
    return plan.seq


def test_gate_list_shows_pending(tmp_path, capsys):
    d = str(tmp_path / "led")
    run_seq = _seed_pending(d)
    rc = main(["gate", "list", "--ledger", d, "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["pending"][0]["run_seq"] == run_seq
    assert out["pending"][0]["wave"] == 1
    assert out["pending"][0]["tasks"] == ["T2"]


def test_gate_approve_resolves(tmp_path, capsys):
    d = str(tmp_path / "led")
    run_seq = _seed_pending(d)
    rc = main(["gate", "approve", "--ledger", d, "--run-seq", str(run_seq), "--wave", "1", "--approver", "op", "--note", "ok"])
    assert rc == 0
    led = Ledger(FileStorage(d))
    assert gate_resolution(led, run_seq, 1) == "approved"


def test_gate_reject_resolves(tmp_path):
    d = str(tmp_path / "led")
    run_seq = _seed_pending(d)
    rc = main(["gate", "reject", "--ledger", d, "--run-seq", str(run_seq), "--wave", "1", "--approver", "op", "--reason", "unsafe"])
    assert rc == 0
    led = Ledger(FileStorage(d))
    assert gate_resolution(led, run_seq, 1) == "rejected"


def test_gate_edit_resolves_with_edits(tmp_path):
    d = str(tmp_path / "led")
    run_seq = _seed_pending(d)
    rc = main([
        "gate", "edit", "--ledger", d, "--run-seq", str(run_seq), "--wave", "1",
        "--approver", "op", "--edit", "T2=NEW",
    ])
    assert rc == 0
    led = Ledger(FileStorage(d))
    assert gate_resolution(led, run_seq, 1) == "edited"
    assert gate_edits(led, run_seq, 1) == {"T2": "NEW"}


def _seed_pending_with_deadline(directory):
    led = Ledger(FileStorage(directory))
    req = led.append(actor="client", kind="request", payload={"tasks": ["T1", "T2"]})
    plan = led.append(
        actor="dispatch", kind="plan", payload={"waves": [["T1"], ["T2"]], "edges": []},
        causal_parent=req.seq,
    )
    led.append(
        actor="dispatch", kind="gate_pending",
        payload={
            "run_seq": plan.seq, "wave": 1, "tasks": ["T2"], "question": "ship?",
            "requested_by": "dispatch", "deadline": 1234.0, "on_expiry": "approve",
        },
        causal_parent=plan.seq,
    )
    return plan.seq


def test_gate_list_json_surfaces_deadline(tmp_path, capsys):
    d = str(tmp_path / "led")
    _seed_pending_with_deadline(d)
    rc = main(["gate", "list", "--ledger", d, "--json"])
    assert rc == 0
    gate = json.loads(capsys.readouterr().out)["pending"][0]
    assert gate["deadline"] == 1234.0
    assert gate["on_expiry"] == "approve"


def test_gate_list_text_shows_deadline(tmp_path, capsys):
    d = str(tmp_path / "led")
    _seed_pending_with_deadline(d)
    rc = main(["gate", "list", "--ledger", d])
    assert rc == 0
    out = capsys.readouterr().out
    assert "deadline=1234" in out
    assert "on_expiry=approve" in out


def test_gate_no_subcommand_prints_help(capsys):
    rc = main(["gate"])
    assert rc == 1
