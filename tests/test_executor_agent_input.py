"""An agent CLI receives the task on stdin, so a batch shim runs every task.

Falsifiers for review findings F7 and F13. The first 1.15.0 candidate appended
the instruction as the last argument. npm installs claude and codex on Windows as
``.cmd`` shims, and a batch target refuses a line break in any argument, so every
task with an upstream result or done criteria was refused. The codex profile also
starts with ``exec``, so ``--cmd "codex exec"`` passed it twice. Local stand-ins
only; no model is reached.
"""
import asyncio
import json

import pytest
from executor_stand_in import WINDOWS, make_world, stand_in

from forum.command_split import split_command
from forum.dispatch import dispatch_plan
from forum.executor import Assignment, SubprocessExecutor
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task


@pytest.fixture
def world(tmp_path, monkeypatch):
    return make_world(tmp_path, monkeypatch)


def _run(executor, instruction="hi"):
    return asyncio.run(executor.run(Assignment("T1", "worker", instruction)))


def _seen(record):
    with open(record, encoding="utf-8") as fh:
        return json.load(fh)


def _ledger():
    ticks = iter(float(t) for t in range(1, 10_000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def test_a_dependent_task_reaches_an_agent_cli(world):
    record = str(world["tmp"] / "claude.json")
    stand_in(str(world["bin"]), "claude", record)  # claude.cmd on Windows, as npm installs it
    plan = Plan((Task("T1", "x", "draft the api", ()),
                 Task("T2", "x", "review the draft", ("T1",))))
    results = asyncio.run(dispatch_plan(plan, _ledger(), SubprocessExecutor(["claude", "-p"])))
    assert results["T2"].ok is True, results["T2"].output
    seen = _seen(record)
    assert "Upstream results you build on" in seen["stdin"]


def test_a_task_with_done_criteria_reaches_an_agent_cli(world):
    record = str(world["tmp"] / "claude.json")
    stand_in(str(world["bin"]), "claude", record)
    plan = Plan((Task("T1", "x", "draft the api", (), done_when=("tests pass",)),))
    results = asyncio.run(dispatch_plan(plan, _ledger(), SubprocessExecutor(["claude", "-p"])))
    assert results["T1"].ok is True, results["T1"].output
    assert "Done criteria" in _seen(record)["stdin"]


def test_an_agent_cli_never_sees_the_instruction_as_an_argument(world):
    record = str(world["tmp"] / "claude.json")
    stand_in(str(world["bin"]), "claude", record)
    result = _run(SubprocessExecutor(["claude", "-p"]), instruction='ship it & say "done" 100%')
    assert result.ok is True, result.output
    seen = _seen(record)
    assert seen["stdin"] == 'ship it & say "done" 100%'
    assert all("ship it" not in arg for arg in seen["args"])


def test_codex_reads_the_task_from_stdin(world):
    record = str(world["tmp"] / "codex.json")
    stand_in(str(world["bin"]), "codex", record)
    result = _run(SubprocessExecutor(["codex"]), instruction="summarize\nthe notes")
    assert result.ok is True, result.output
    seen = _seen(record)
    assert seen["args"][0] == "exec"
    assert seen["args"][-1] == "-"
    assert seen["stdin"] == "summarize\nthe notes"


def test_codex_exec_is_passed_once(world):
    record = str(world["tmp"] / "codex.json")
    stand_in(str(world["bin"]), "codex", record)
    result = _run(SubprocessExecutor(split_command("codex exec")), instruction="summarize")
    assert result.ok is True, result.output
    assert _seen(record)["args"].count("exec") == 1


@pytest.mark.skipif(not WINDOWS, reason="cmd.exe metacharacter refusal is a Windows batch concern")
def test_a_plain_batch_command_still_takes_the_instruction_as_an_argument(world):
    # A command that is not an agent CLI keeps the documented contract: the
    # instruction is its last argument, and a batch target refuses metacharacters.
    from executor_stand_in import BATCH_RECORDER

    record = str(world["tmp"] / "model.json")
    stand_in(str(world["bin"]), "model", record, body_src=BATCH_RECORDER)
    assert _run(SubprocessExecutor(["model"]), instruction="plan the api").ok is True
    assert _seen(record)["args"][-1] == "plan the api"
