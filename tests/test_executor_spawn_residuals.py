r"""A planted program never runs through routes the first working-folder guard missed.

Forum 1.15.0 kept the working folder out of a bare-name lookup, but its own guard
compared PATH entries by name only and handed each entry to the child as written.
Three routes still reached a planted program:

- an alias of the working folder the name check misses but file identity catches
  (the ``\\?\`` long-path prefix, the ``\\localhost\C$`` admin share, a bind mount);
- a junction on PATH pointing outside at the check, repointed into the working folder
  before the child starts, in forum's own lookup or in the child's bare-name lookup;
- a PATH entry quoted so cmd.exe reads it as the working folder or a folder below it
  (``"<folder>"\bin`` or ``<parent>\"<folder>"``), handed to a child whose own
  bare-name lookup then finds a plant there.

Every test drives forum's public executor, ``SubprocessExecutor``. The race tests
repoint the link inside the vendored helper's ``bounded_run``, which forum's route
calls after the lookup and the child's PATH are built, in 1.0.0 and 1.0.1 alike.
Each test fails on the released version (1.15.0: vendored safe_spawn 1.0.0 behind
forum's own guard) by an assertion that shows the plant winning the lookup or
running, and passes after the upgrade to 1.0.1. Real processes run against local
stand-ins; no model is reached.
"""
import asyncio
import os
import shutil
import subprocess
import sys

import pytest
from executor_stand_in import SYSTEM32, WINDOWS, make_world, plant_binary, stand_in

from forum._vendor import safe_spawn
from forum.executor import Assignment, SubprocessExecutor

windows_only = pytest.mark.skipif(not WINDOWS, reason="Windows path semantics")
LINUX_ROOT = sys.platform.startswith("linux") and hasattr(os, "geteuid") and os.geteuid() == 0

# npm's cmd-shim template: with no node.exe beside it, it runs "node" by bare name.
NPM_SHIM = ("@ECHO off\r\nGOTO start\r\n:find_dp0\r\nSET dp0=%~dp0\r\nEXIT /b\r\n:start\r\n"
            "SETLOCAL\r\nCALL :find_dp0\r\n\r\nIF EXIST \"%dp0%\\node.exe\" (\r\n"
            "  SET \"_prog=%dp0%\\node.exe\"\r\n) ELSE (\r\n  SET \"_prog=node\"\r\n"
            "  SET PATHEXT=%PATHEXT:;.JS;=;%\r\n)\r\n\r\n"
            "endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & \"%_prog%\"  "
            "\"%dp0%\\node_modules\\tool\\cli.js\" %*\r\n")


@pytest.fixture
def world(tmp_path, monkeypatch):
    return make_world(tmp_path, monkeypatch)


def _run(executor, instruction="hi"):
    return asyncio.run(executor.run(Assignment("T1", "worker", instruction)))


def _write(path, text, newline=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline=newline) as fh:
        fh.write(text)
    return path


def _junction(target, link):
    subprocess.run([os.path.join(SYSTEM32, "cmd.exe"), "/c", "mklink", "/J", link, target],
                   check=True, capture_output=True)


def _decoy_cmd(folder, name, marker):
    return _write(os.path.join(folder, name + ".cmd"),
                  f'@echo off\r\necho x> "{marker}"\r\necho PLANTED\r\n', newline="")


def _decoy_sh(folder, name, marker):
    path = _write(os.path.join(folder, name), f'#!/bin/sh\necho x > "{marker}"\necho PLANTED\n')
    os.chmod(path, 0o755)
    return path


def _record_starts(monkeypatch):
    """The executables forum's route starts, read at the helper's start seam."""
    started, start = [], safe_spawn.bounded_run

    def record_then_start(argv, **kw):
        started.append(argv[0])
        return start(argv, **kw)

    monkeypatch.setattr(safe_spawn, "bounded_run", record_then_start)
    return started


def _repoint_before_start(monkeypatch, link, target):
    """Replay the race: once the lookup and the child's PATH are built, repoint `link`
    at `target`, then start the child."""
    start = safe_spawn.bounded_run

    def repoint_then_start(argv, **kw):
        try:
            os.rmdir(link)
        except OSError:
            os.remove(link)
        _junction(target, link)
        return start(argv, **kw)

    monkeypatch.setattr(safe_spawn, "bounded_run", repoint_then_start)


def _npm_tool_and_node(world):
    """An npm-style `tool` shim in bin and a real `node` stand-in; the node folder."""
    _write(str(world["bin"] / "tool.cmd"), NPM_SHIM, newline="")
    os.makedirs(world["project"] / "node_modules" / "tool", exist_ok=True)
    return os.path.dirname(stand_in(str(world["tmp"] / "nodejs"), "node",
                                    str(world["tmp"] / "node.json")))


def _alias_never_wins(world, monkeypatch, spelled, label):
    # A .exe beats the real .cmd shim, so a kept alias entry lets the planted claude.exe
    # displace the real tool; CreateProcess starts an .exe by an aliased path.
    project = str(world["project"])
    stand_in(str(world["bin"]), "claude", str(world["tmp"] / "claude.json"))
    plant_binary(project, "claude", str(world["tmp"] / "PLANTED-RAN"))
    monkeypatch.setenv("PATH", os.pathsep.join([spelled, str(world["bin"]), SYSTEM32]))
    started = _record_starts(monkeypatch)
    result = _run(SubprocessExecutor(["claude"], profile="claude"))
    assert len(started) == 1, "the executor started nothing"
    assert not os.path.samefile(os.path.dirname(started[0]), project), (
        f"forum's lookup returned a planted claude.exe through the {label} alias")
    assert result.output == "STUB-ANSWER", f"a planted claude.exe won through the {label} alias"


@windows_only
def test_a_long_path_prefix_alias_of_the_working_folder_never_runs_the_plant(world, monkeypatch):
    # \\?\C:\...\project names the project folder; a name-only guard keeps it.
    spelled = "\\\\?\\" + str(world["project"])
    assert os.path.samefile(spelled, str(world["project"]))
    _alias_never_wins(world, monkeypatch, spelled, "\\\\?\\")


@windows_only
def test_an_admin_share_alias_of_the_working_folder_never_runs_the_plant(world, monkeypatch):
    p = str(world["project"])
    unc = "\\\\localhost\\" + p[0] + "$" + p[2:]
    if not os.path.isdir(unc) or not os.path.samefile(unc, p):
        pytest.skip("the admin share does not reach this folder here")
    _alias_never_wins(world, monkeypatch, unc, "admin share")


@pytest.mark.skipif(not LINUX_ROOT, reason="a bind mount needs Linux and root")
def test_a_bind_mount_alias_of_the_working_folder_never_runs_the_plant(world, monkeypatch):
    # Two names for one folder, no link between them: only file identity ties them.
    project, marker = str(world["project"]), world["tmp"] / "PLANTED-RAN"
    _decoy_sh(project, "tool", str(marker))
    stand_in(str(world["bin"]), "tool", str(world["tmp"] / "tool.json"))
    mnt = str(world["tmp"] / "mnt")
    os.makedirs(mnt)
    mount, umount = shutil.which("mount"), shutil.which("umount")
    subprocess.run([mount, "--bind", project, mnt], check=True)
    try:
        assert os.path.realpath(mnt) != os.path.realpath(project)
        assert os.path.samefile(mnt, project)
        monkeypatch.setenv("PATH", os.pathsep.join([mnt, str(world["bin"]), "/usr/bin", "/bin"]))
        started = _record_starts(monkeypatch)
        result = _run(SubprocessExecutor(["tool"]))
        assert len(started) == 1, "the executor started nothing"
        assert not os.path.samefile(os.path.dirname(started[0]), project), (
            "forum's lookup returned a planted tool through a bind-mount alias")
        assert "PLANTED" not in result.output and not marker.exists(), (
            "a planted tool ran through a bind-mount alias the name check misses")
        assert result.output == "STUB-ANSWER"
    finally:
        subprocess.run([umount, mnt], check=True)


@windows_only
def test_a_quoted_entry_never_hands_a_child_a_node_planted_below_the_folder(world, monkeypatch):
    # "<project>"\bin: cmd.exe reads it as <project>\bin. Forum's own lookup skips it
    # (the inner quote names no folder), but the child's npm shim looks up `node` on the
    # PATH it inherits, and cmd.exe there reads the entry as the folder and finds the plant.
    project, marker = world["project"], world["tmp"] / "NODE-RAN"
    node_dir = _npm_tool_and_node(world)
    _decoy_cmd(str(project / "bin"), "node", str(marker))
    entry = f'"{project}"\\bin'
    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join([entry, node_dir, str(world["bin"]), SYSTEM32]))
    result = _run(SubprocessExecutor(["tool"]))
    assert "PLANTED" not in result.output and not marker.exists(), (
        "a node planted below the working folder ran through the quoted PATH entry")
    assert result.output == "STUB-ANSWER"


@windows_only
def test_a_quoted_folder_name_never_hands_a_child_the_working_folder_itself(world, monkeypatch):
    # <parent>\"project": cmd.exe drops every quote and reads the working folder itself.
    project, marker = world["project"], world["tmp"] / "NODE-RAN"
    node_dir = _npm_tool_and_node(world)
    _decoy_cmd(str(project), "node", str(marker))
    entry = f'{world["tmp"]}\\"{project.name}"'
    monkeypatch.setenv("PATH", os.pathsep.join([entry, node_dir, str(world["bin"]), SYSTEM32]))
    result = _run(SubprocessExecutor(["tool"]))
    assert "PLANTED" not in result.output and not marker.exists(), (
        "a node planted in the working folder ran through the quoted folder name")
    assert result.output == "STUB-ANSWER"


@windows_only
def test_a_junction_repointed_between_the_check_and_the_start_never_starts_the_plant(
        world, monkeypatch):
    # A junction on PATH points at a trusted folder when the guard checks it, then is
    # repointed into the working folder before the child starts. The helper anchors each
    # kept entry to its real folder at check time, so the repoint has no effect.
    trusted = str(world["tmp"] / "trusted")
    stand_in(trusted, "tool", str(world["tmp"] / "tool.json"))
    marker = world["tmp"] / "PLANTED-RAN"
    _decoy_cmd(str(world["project"]), "tool", str(marker))
    link = str(world["tmp"] / "linkdir")
    _junction(trusted, link)
    monkeypatch.setenv("PATH", os.pathsep.join([link, SYSTEM32]))
    _repoint_before_start(monkeypatch, link, str(world["project"]))
    result = _run(SubprocessExecutor(["tool"]))
    assert os.path.samefile(link, str(world["project"])), "the race was not replayed"
    assert "PLANTED" not in result.output and not marker.exists(), (
        "a junction repointed after the check started the plant")
    assert result.output == "STUB-ANSWER"


@windows_only
def test_a_junction_repointed_after_the_childs_path_is_built_never_hands_it_the_plant(
        world, monkeypatch):
    # The same race in the child's own lookup: the npm shim looks up `node` on the PATH
    # forum hands it, and a junction there is repointed into the working folder after
    # forum built that PATH and before the child starts.
    marker = world["tmp"] / "NODE-RAN"
    node_dir = _npm_tool_and_node(world)
    _decoy_cmd(str(world["project"]), "node", str(marker))
    link = str(world["tmp"] / "nodelink")
    _junction(node_dir, link)
    monkeypatch.setenv("PATH", os.pathsep.join([link, str(world["bin"]), SYSTEM32]))
    _repoint_before_start(monkeypatch, link, str(world["project"]))
    result = _run(SubprocessExecutor(["tool"]))
    assert os.path.samefile(link, str(world["project"])), "the race was not replayed"
    assert "PLANTED" not in result.output and not marker.exists(), (
        "a junction repointed after the child's PATH was built handed it the planted node")
    assert result.output == "STUB-ANSWER"


def test_the_pinned_helper_carries_the_fix():
    # A guard for the guard: the routes above are closed only from 1.0.1 on.
    assert safe_spawn.SAFE_SPAWN_VERSION == "1.0.1"
