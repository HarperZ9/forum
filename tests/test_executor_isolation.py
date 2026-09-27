"""SubprocessExecutor starts a child through the vendored safe_spawn.

Falsifiers for the audit S1/S2 findings: 1.14.0 started the command by bare name
from the server's folder, with the whole environment and no isolation flags. Each
test runs a real process; a stand-in named like the CLI stands in for the model.
No model is reached.
"""
import asyncio
import json
import os

import pytest
from executor_stand_in import FAKE_KEY, WINDOWS, make_world, plant_binary, stand_in

from forum.executor import Assignment, SubprocessExecutor

CLAUDE_PROFILE = ["--setting-sources", "user", "--strict-mcp-config", "--tools", ""]


@pytest.fixture
def world(tmp_path, monkeypatch):
    return make_world(tmp_path, monkeypatch)


def _run(executor, instruction="hi"):
    return asyncio.run(executor.run(Assignment("T1", "worker", instruction)))


def _seen(record):
    with open(record, encoding="utf-8") as fh:
        return json.load(fh)


def test_a_planted_executable_in_the_working_folder_does_not_run(world):
    record = str(world["tmp"] / "claude.json")
    stand_in(str(world["bin"]), "claude", record)
    marker = world["tmp"] / "PLANTED-RAN"
    plant_binary(str(world["project"]), "claude", str(marker))
    result = _run(SubprocessExecutor(["claude"], profile="claude"))
    assert result.ok is True
    assert result.output == "STUB-ANSWER"
    assert not marker.exists()


def test_a_planted_project_settings_hook_leaves_no_marker(world):
    record = str(world["tmp"] / "claude.json")
    stand_in(str(world["bin"]), "claude", record)
    _run(SubprocessExecutor(["claude"], profile="claude"))
    seen = _seen(record)
    assert not world["marker"].exists()
    assert seen["listing"] == []  # a new empty private working folder
    assert os.path.normcase(seen["cwd"]) != os.path.normcase(str(world["project"]))
    assert seen["args"][-len(CLAUDE_PROFILE):] == CLAUDE_PROFILE


def test_the_child_sees_only_allowlisted_variables(world):
    record = str(world["tmp"] / "claude.json")
    stand_in(str(world["bin"]), "claude", record)
    _run(SubprocessExecutor(["claude"], profile="claude"))
    env = _seen(record)["env"]
    assert FAKE_KEY not in json.dumps(env)
    if WINDOWS:
        upper = {k.upper(): v for k, v in env.items()}
        assert upper["NODEFAULTCURRENTDIRECTORYINEXEPATH"] == "1"


def test_a_named_child_variable_reaches_the_child(world, monkeypatch):
    record = str(world["tmp"] / "claude.json")
    stand_in(str(world["bin"]), "claude", record)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    _run(SubprocessExecutor(["claude"], profile="claude", allow_env=("HTTPS_PROXY",)))
    env = {k.upper(): v for k, v in _seen(record)["env"].items()}
    assert env["HTTPS_PROXY"] == "http://proxy.invalid:3128"
    assert FAKE_KEY not in json.dumps(env)


@pytest.mark.skipif(not WINDOWS, reason="cmd.exe metacharacter refusal is a Windows batch concern")
def test_a_batch_target_refuses_cmd_metacharacters(world):
    from executor_stand_in import BATCH_RECORDER

    record = str(world["tmp"] / "model.json")
    stand_in(str(world["bin"]), "model", record, body_src=BATCH_RECORDER)
    result = _run(SubprocessExecutor(["model"]), instruction='do x & del %TEMP%')
    assert result.ok is False
    assert "UNSAFE_ARGUMENT" in result.output
    assert not os.path.exists(record)  # the target was never started


@pytest.mark.skipif(not WINDOWS, reason="cmd.exe metacharacter refusal is a Windows batch concern")
def test_a_batch_target_runs_a_clean_instruction(world):
    from executor_stand_in import BATCH_RECORDER

    record = str(world["tmp"] / "model.json")
    stand_in(str(world["bin"]), "model", record, body_src=BATCH_RECORDER)
    result = _run(SubprocessExecutor(["model"]), instruction="plan the api cleanly")
    assert result.ok is True
    assert _seen(record)["args"][-1] == "plan the api cleanly"


def test_an_unproven_agent_cli_is_refused_by_default(world):
    record = str(world["tmp"] / "gemini.json")
    stand_in(str(world["bin"]), "gemini", record)
    result = _run(SubprocessExecutor(["gemini"], profile="gemini"))
    assert result.ok is False
    assert "GRANT_REQUIRED" in result.output
    assert not os.path.exists(record)


def test_an_unproven_agent_cli_runs_when_the_launch_grants_it(world, monkeypatch):
    record = str(world["tmp"] / "gemini.json")
    stand_in(str(world["bin"]), "gemini", record)
    result = _run(SubprocessExecutor(["gemini"], profile="gemini", grants=("gemini",)))
    assert result.ok is True


def test_a_python_target_gets_safe_path(world):
    # A python target gets PYTHONSAFEPATH=1 (and -P), so the working folder is not
    # prepended to sys.path and a planted module beside it is not importable. -P is
    # consumed by the interpreter, so the child sees it through the environment.
    import sys

    record = str(world["tmp"] / "py.json")
    body = str(world["bin"] / "reporter.py")
    env_report = (
        "import json, os\n"
        f"open({record!r}, 'w').write(json.dumps("
        "{'safepath': os.environ.get('PYTHONSAFEPATH'), 'cwd_files': sorted(os.listdir('.'))}))\n"
        "print('STUB-ANSWER')\n"
    )
    with open(body, "w", encoding="utf-8") as fh:
        fh.write(env_report)
    result = _run(SubprocessExecutor([sys.executable, body]), instruction="x")
    assert result.ok is True
    seen = _seen(record)
    assert seen["safepath"] == "1"
    assert seen["cwd_files"] == []  # a private empty working folder


def test_override_variable_must_be_absolute(world, monkeypatch):
    record = str(world["tmp"] / "claude.json")
    real = stand_in(str(world["bin"]), "claude", record)
    monkeypatch.setenv("FORUM_CLAUDE_CLI", os.path.basename(real))
    result = _run(SubprocessExecutor(["claude"], profile="claude", override_var="FORUM_CLAUDE_CLI"))
    assert result.ok is False
    assert "BAD_OVERRIDE" in result.output
    monkeypatch.setenv("FORUM_CLAUDE_CLI", real)
    assert _run(SubprocessExecutor(["claude"], profile="claude",
                                   override_var="FORUM_CLAUDE_CLI")).output == "STUB-ANSWER"


def test_a_missing_command_is_reported_not_raised(world):
    result = _run(SubprocessExecutor(["definitely-not-installed-xyz"]))
    assert result.ok is False
    assert "NOT_FOUND" in result.output


def test_the_cli_wires_the_claude_profile_from_a_bare_command(monkeypatch):
    # forum submit --cmd "claude -p" should pick up the claude isolation profile.
    from forum.cli import _make_executor, build_parser

    args = build_parser().parse_args(["submit", "do x", "--cmd", "claude -p"])
    executor = _make_executor(args)
    assert executor._profile == "claude"
    assert executor._command == ["claude", "-p"]
