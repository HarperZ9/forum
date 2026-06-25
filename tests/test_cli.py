import json

import pytest

from forum.cli import _cmd_mcp, _cmd_serve, build_parser, main
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


def test_route_decides_a_lane(capsys):
    rc = main(["route", "build the api database server endpoint"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decided"] == "backend"


def test_submit_without_executor_is_guided_error(capsys, tmp_path):
    rc = main(["submit", "do something", "--ledger", str(tmp_path)])
    assert rc == 2
    assert "needs a model executor" in capsys.readouterr().err


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


def test_submit_flags_parse():
    args = build_parser().parse_args(["submit", "do x", "--api", "--model", "claude-opus-4-8"])
    assert args.api is True and args.model == "claude-opus-4-8"


def test_chat_url_flag_parses_for_a_local_model():
    args = build_parser().parse_args(
        ["submit", "do x", "--chat-url", "http://localhost:11434/v1/chat/completions", "--model", "llama3"]
    )
    assert args.chat_url.endswith("/v1/chat/completions")
    assert args.model == "llama3"
