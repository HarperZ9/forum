import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from forum.cli import _cmd_mcp, _cmd_serve, _make_executor, build_parser, main
from forum.ledger import Ledger
from forum.storage import FileStorage


def _seed(directory):
    led = Ledger(FileStorage(directory))
    led.append(actor="client", kind="request", payload={"text": "hi"})
    led.append(actor="worker", kind="result", payload={"out": "done"})
    return led


def test_no_command_prints_help_and_returns_1(capsys):
    assert main([]) == 1
    assert "usage: forum" in capsys.readouterr().out


def test_version_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "forum" in capsys.readouterr().out


def test_package_module_entrypoint_runs_version():
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    result = subprocess.run(
        [sys.executable, "-m", "forum", "--version"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0
    assert "forum " in result.stdout


def test_source_checkout_module_entrypoint_runs_without_pythonpath():
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "-m", "forum", "--version"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "forum " in result.stdout


def test_route_decides_a_lane(capsys):
    rc = main(["route", "build the api database server endpoint"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decided"] == "backend"


def test_route_accepts_json_flag_for_operator_consistency(capsys):
    rc = main(["route", "build the api database server endpoint", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decided"] == "backend"
    assert "candidates" in payload


def test_route_includes_human_frame(capsys):
    rc = main([
        "route",
        "build eval gated model promotion for a self improving daemon",
        "--json",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decided"] == "model-foundry"
    assert payload["frame"]["schema"] == "forum.route-frame/v1"
    assert payload["frame"]["posture"] == "architect"
    assert payload["frame"]["delivery_profile"] == "engineer"


def test_submit_without_executor_is_guided_error(capsys, tmp_path):
    rc = main(["submit", "do something", "--ledger", str(tmp_path)])
    assert rc == 2
    assert "needs a model executor" in capsys.readouterr().err


def test_submit_json_returns_answer_and_receipt(capsys, tmp_path):
    import sys

    model = tmp_path / "model.py"
    model.write_text(
        "import sys\n"
        "text = sys.argv[1]\n"
        "if 'You are a planner' in text:\n"
        "    print('{\"tasks\":[{\"id\":\"T1\",\"agent\":\"backend\",\"instruction\":\"x\",\"depends_on\":[]}]}')\n"
        "elif 'Judge whether the output satisfies' in text:\n"
        "    print('{\"ok\":true,\"score\":0.9,\"reason\":\"ok\"}')\n"
        "elif 'Write the final answer' in text:\n"
        "    print('Done from cli.')\n"
        "else:\n"
        "    print('handled')\n",
        encoding="utf-8",
    )

    rc = main([
        "submit", "design an api", "--ledger", str(tmp_path / "ledger"),
        "--cmd", f'{sys.executable} {model}', "--json",
        "--delivery-profile", "engineer",
    ])
    body = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert body["answer"] == "Done from cli."
    assert body["receipt"]["schema"] == "project-telos.action-receipt/v1"
    assert body["receipt"]["model"]["id"] == "SubprocessExecutor"
    assert body["receipt"]["delivery_profile"]["requested"] == "engineer"
    assert body["receipt"]["delivery_profile"]["selected"] == "engineer"
    assert body["receipt"]["delivery_profile"]["source"] == "explicit"
    assert body["receipt"]["delivery_profile"]["checks"] == 1
    assert body["receipt"]["route_frame"]["schema"] == "forum.route-frame/v1"
    assert body["receipt"]["route_frame"]["delivery_profile"] == "engineer"
    assert body["receipt"]["verification"]["verdict"] == "MATCH"

def test_ledger_verify(capsys, tmp_path):
    _seed(str(tmp_path))
    rc = main(["ledger", "verify", "--ledger", str(tmp_path)])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"chain": True, "deep": True}


def test_ledger_show_lists_entries(capsys, tmp_path):
    _seed(str(tmp_path))
    rc = main(["ledger", "show", "--ledger", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "client" in out and "worker" in out


def test_ledger_replay_dumps_prefix(capsys, tmp_path):
    _seed(str(tmp_path))
    rc = main(["ledger", "replay", "0", "--ledger", str(tmp_path)])
    entries = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert [e["seq"] for e in entries] == [0]


def test_ledger_get_returns_entry(capsys, tmp_path):
    _seed(str(tmp_path))
    rc = main(["ledger", "get", "1", "--ledger", str(tmp_path)])
    entry = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert entry["kind"] == "result"


def test_ledger_get_missing_returns_1(capsys, tmp_path):
    _seed(str(tmp_path))
    rc = main(["ledger", "get", "99", "--ledger", str(tmp_path)])
    assert rc == 1
    assert "no ledger entry" in capsys.readouterr().err


def test_ledger_without_subcommand_shows_ledger_help(capsys, tmp_path):
    assert main(["ledger"]) == 1
    out = capsys.readouterr().out
    assert "verify" in out and "replay" in out  # the ledger subcommands, not top-level help


def test_serve_and_mcp_wire_to_their_handlers():
    # Parse only (do not run the long-lived servers); confirm dispatch + flags.
    serve_args = build_parser().parse_args(["serve", "--port", "9999", "--host", "0.0.0.0"])
    assert serve_args.func is _cmd_serve
    assert serve_args.port == 9999 and serve_args.host == "0.0.0.0"
    mcp_args = build_parser().parse_args(["mcp", "--ledger", "x"])
    assert mcp_args.func is _cmd_mcp
    assert mcp_args.ledger == "x"



def test_cmd_executor_preserves_windows_paths(monkeypatch):
    import forum.cli as cli

    monkeypatch.setattr(cli.os, "name", "nt")
    args = build_parser().parse_args([
        "submit", "do x", "--cmd", r"C:\Tools\model.exe C:\tmp\adapter.py",
    ])
    executor = _make_executor(args)

    assert executor._command == [r"C:\Tools\model.exe", r"C:\tmp\adapter.py"]

def test_submit_flags_parse():
    args = build_parser().parse_args(["submit", "do x", "--api", "--model", "claude-opus-4-8"])
    assert args.api is True and args.model == "claude-opus-4-8"


def test_chat_url_flag_parses_for_a_local_model():
    args = build_parser().parse_args(
        ["submit", "do x", "--chat-url", "http://localhost:11434/v1/chat/completions", "--model", "llama3"]
    )
    assert args.chat_url.endswith("/v1/chat/completions")
    assert args.model == "llama3"


def test_budget_flags_parse():
    args = build_parser().parse_args(["submit", "do x", "--max-model-calls", "5", "--max-seconds", "30"])
    assert args.max_model_calls == 5
    assert args.max_seconds == 30.0


def test_context_budget_flags_parse():
    parser = build_parser()
    args = parser.parse_args([
        "submit",
        "build",
        "--cmd",
        "echo",
        "--context-token-budget",
        "100",
        "--request-context-token-budget",
        "50",
        "--task-context-token-budget",
        "25",
        "--upstream-token-budget",
        "10",
    ])
    assert args.context_token_budget == 100
    assert args.request_context_token_budget == 50
    assert args.task_context_token_budget == 25
    assert args.upstream_token_budget == 10


def test_delivery_profile_submit_flag_parses():
    args = build_parser().parse_args([
        "submit",
        "do x",
        "--cmd",
        "echo",
        "--delivery-profile",
        "engineer",
    ])
    assert args.delivery_profile == "engineer"


def test_submit_checkpoint_each_wave_flag_parses():
    args = build_parser().parse_args([
        "submit",
        "do x",
        "--cmd",
        "echo",
        "--checkpoint-each-wave",
    ])
    assert args.checkpoint_each_wave is True


def test_ledger_summary_json(capsys, tmp_path):
    _seed(str(tmp_path))
    rc = main(["ledger", "summary", "--ledger", str(tmp_path), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["entries"] == 2
    assert "checkpoint" in out and out["verified"] is True


def test_ledger_capsule_json(capsys, tmp_path):
    _seed(str(tmp_path))
    rc = main(["ledger", "capsule", "--ledger", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["schema"] == "forum.context-capsule/v1"
    assert payload["checkpoint"]
    assert payload["verified"] is True


def test_ledger_room_json(capsys, tmp_path):
    _seed(str(tmp_path))
    rc = main(["ledger", "room", "--ledger", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["schema"] == "forum.run-room/v1"
    assert payload["request"]["text"] == "hi"
    assert payload["verified"] is True


def test_ledger_capsule_text(capsys, tmp_path):
    _seed(str(tmp_path))
    rc = main(["ledger", "capsule", "--ledger", str(tmp_path), "--text"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Forum context capsule" in out
    assert "checkpoint:" in out


def test_submit_use_capsule_context_witnesses_context(capsys, tmp_path):
    import sys

    ledger_dir = tmp_path / "ledger"
    _seed(str(ledger_dir))
    model = tmp_path / "model.py"
    model.write_text(
        "import sys\n"
        "text = sys.argv[1]\n"
        "if 'You are a planner' in text:\n"
        "    assert 'Forum context capsule' in text\n"
        "    print('{\"tasks\":[{\"id\":\"T1\",\"agent\":\"backend\",\"instruction\":\"x\",\"depends_on\":[]}]}')\n"
        "elif 'Judge whether the output satisfies' in text:\n"
        "    print('{\"ok\":true,\"score\":0.9,\"reason\":\"ok\"}')\n"
        "elif 'Write the final answer' in text:\n"
        "    print('Done with capsule.')\n"
        "else:\n"
        "    print('handled')\n",
        encoding="utf-8",
    )
    rc = main([
        "submit",
        "design an api",
        "--ledger",
        str(ledger_dir),
        "--cmd",
        f"{sys.executable} {model}",
        "--json",
        "--use-capsule-context",
        "--context-token-budget",
        "1000",
    ])
    body = json.loads(capsys.readouterr().out)
    led = Ledger(FileStorage(str(ledger_dir)))
    contexts = [led.get_payload(e.payload_hash)["context"] for e in led.query(kind="context")]
    assert rc == 0
    assert body["answer"] == "Done with capsule."
    assert any("Forum context capsule" in context for context in contexts)


def test_bench_compares_two_ledgers(capsys, tmp_path):
    a = str(tmp_path / "a")
    b = str(tmp_path / "b")
    _seed(a)
    _seed(b)
    Ledger(FileStorage(b)).append(actor="client", kind="request", payload={"t": "extra"})
    rc = main(["bench", a, b, "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["delta"]["requests"] == 1
    assert out["delta"]["entries"] == 1
