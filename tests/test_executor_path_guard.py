"""A command is never found inside the folder the server runs in, however PATH reaches it.

Falsifiers for review finding F3. The first 1.15.0 candidate skipped only relative
PATH entries, so an absolute entry inside the working folder (npm puts
``<project>/node_modules/.bin`` on PATH), a junction pointing into it, or a
drive-relative name such as ``C:model`` still started a program planted there.
Each test starts real processes against local stand-ins; no model is reached.
"""
import asyncio
import json
import os
import shutil
import subprocess

import pytest
from executor_stand_in import SYSTEM32, WINDOWS, make_world, plant_binary, stand_in

from forum.executor import Assignment, SubprocessExecutor

windows_only = pytest.mark.skipif(not WINDOWS, reason="Windows path semantics")


@pytest.fixture
def world(tmp_path, monkeypatch):
    return make_world(tmp_path, monkeypatch)


def _run(executor, instruction="hi"):
    return asyncio.run(executor.run(Assignment("T1", "worker", instruction)))


def _base_path():
    return [SYSTEM32] if WINDOWS else ["/usr/bin", "/bin"]


def _seen(record):
    with open(record, encoding="utf-8") as fh:
        return json.load(fh)


def test_a_path_entry_inside_the_working_folder_is_skipped(world, monkeypatch):
    record = str(world["tmp"] / "claude.json")
    stand_in(str(world["bin"]), "claude", record)
    inside = world["project"] / "node_modules" / ".bin"
    planted = world["tmp"] / "PLANTED-RAN"
    plant_binary(str(inside), "claude", str(planted))
    monkeypatch.setenv("PATH", os.pathsep.join([str(inside), str(world["bin"]), *_base_path()]))
    result = _run(SubprocessExecutor(["claude"]))
    assert not planted.exists()
    assert result.output == "STUB-ANSWER"


def test_the_child_path_leaves_out_entries_inside_the_working_folder(world, monkeypatch):
    # A batch shim (npm's claude.cmd) looks up `node` on the PATH it is given, so
    # the entry must be gone from the child's PATH too, not only from the lookup.
    record = str(world["tmp"] / "claude.json")
    stand_in(str(world["bin"]), "claude", record)
    inside = world["project"] / "node_modules" / ".bin"
    inside.mkdir(parents=True)
    monkeypatch.setenv("PATH", os.pathsep.join([str(inside), str(world["bin"]), *_base_path()]))
    _run(SubprocessExecutor(["claude"]))
    env = {k.upper(): v for k, v in _seen(record)["env"].items()}
    entries = [os.path.normcase(e) for e in env["PATH"].split(os.pathsep) if e]
    assert os.path.normcase(str(inside)) not in entries
    assert os.path.normcase(str(world["bin"])) in entries


def test_a_path_entry_naming_the_working_folder_itself_is_skipped(world, monkeypatch):
    record = str(world["tmp"] / "claude.json")
    stand_in(str(world["bin"]), "claude", record)
    planted = world["tmp"] / "PLANTED-RAN"
    plant_binary(str(world["project"]), "claude", str(planted))
    monkeypatch.setenv("PATH", os.pathsep.join([str(world["project"]), str(world["bin"]),
                                                *_base_path()]))
    result = _run(SubprocessExecutor(["claude"]))
    assert not planted.exists()
    assert result.output == "STUB-ANSWER"


@pytest.mark.skipif(WINDOWS, reason="POSIX symlink; the Windows case is the junction test")
def test_a_symlink_into_the_working_folder_is_skipped(world, monkeypatch):
    record = str(world["tmp"] / "claude.json")
    stand_in(str(world["bin"]), "claude", record)
    inside = world["project"] / "tools"
    planted = world["tmp"] / "PLANTED-RAN"
    plant_binary(str(inside), "claude", str(planted))
    link = world["tmp"] / "linkbin"
    os.symlink(str(inside), str(link))
    monkeypatch.setenv("PATH", os.pathsep.join([str(link), str(world["bin"]), *_base_path()]))
    result = _run(SubprocessExecutor(["claude"]))
    assert not planted.exists()
    assert result.output == "STUB-ANSWER"


@windows_only
def test_a_junction_into_the_working_folder_is_skipped(world, monkeypatch):
    record = str(world["tmp"] / "claude.json")
    stand_in(str(world["bin"]), "claude", record)
    inside = world["project"] / "tools"
    plant_binary(str(inside), "claude", str(world["tmp"] / "PLANTED-RAN"))
    link = world["tmp"] / "linkbin"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(inside)],
                   capture_output=True, check=True)
    monkeypatch.setenv("PATH", os.pathsep.join([str(link), str(world["bin"]), SYSTEM32]))
    result = _run(SubprocessExecutor(["claude"]))
    assert result.output == "STUB-ANSWER"


@windows_only
def test_a_drive_relative_command_name_is_refused(world, monkeypatch):
    drive = os.path.splitdrive(str(world["project"]))[0]
    # tzutil /g prints the time zone and exits 0: a planted program that "works".
    shutil.copy(os.path.join(SYSTEM32, "tzutil.exe"), str(world["project"] / "model.exe"))
    monkeypatch.setenv("PATH", SYSTEM32)
    result = _run(SubprocessExecutor([f"{drive}model"]), instruction="/g")
    assert result.ok is False
    assert result.output.startswith("error: BAD_PATH")


@windows_only
def test_a_drive_relative_name_is_refused_when_path_is_on_another_drive(world, monkeypatch):
    drive = os.path.splitdrive(str(world["project"]))[0]
    other = next((d + "\\" for d in ("D:", "E:", "F:", "G:")
                  if d.upper() != drive.upper() and os.path.isdir(d + "\\")), None)
    if other is None:
        pytest.skip("needs a second drive to hold the only PATH entry")
    shutil.copy(os.path.join(SYSTEM32, "tzutil.exe"), str(world["project"] / "model.exe"))
    monkeypatch.setenv("PATH", other)
    result = _run(SubprocessExecutor([f"{drive}model"]), instruction="/g")
    assert result.ok is False
    assert result.output.startswith("error:")


# What the guard keeps, so a common setup still works. The guard lives in the vendored
# helper now (forum no longer carries its own copy); these pin the guarantees forum
# relies on through the shipped bytes.

def test_the_interpreters_own_folder_stays_on_the_childs_path(monkeypatch):
    # An activated project venv, or a Windows service in System32: forum already runs
    # code from the interpreter's folder, so a lookup there is not a new reach.
    import sys

    from forum._vendor import safe_spawn

    folder = os.path.dirname(sys.executable)
    parent = os.path.dirname(folder)
    home = os.path.normcase(os.path.expanduser("~"))
    if os.path.dirname(parent) == parent or home.startswith(os.path.normcase(parent)):
        pytest.skip("the interpreter's parent folder is a root or holds home here")
    monkeypatch.chdir(parent)
    monkeypatch.setenv("PATH", folder)
    assert safe_spawn.child_env()["PATH"] == folder


def test_the_python_environment_forum_runs_from_stays_on_path(tmp_path, monkeypatch):
    # An activated project venv inside the working folder: the interpreter's own folder
    # stays, while a sibling folder in the same project drops.
    import sys

    from forum._vendor import safe_spawn

    project = tmp_path / "project"
    venv_bin = project / ".venv" / ("Scripts" if WINDOWS else "bin")
    tools = project / "tools"
    venv_bin.mkdir(parents=True)
    tools.mkdir()
    monkeypatch.setattr(sys, "executable", str(venv_bin / ("python.exe" if WINDOWS else "python")))
    monkeypatch.chdir(project)
    monkeypatch.setenv("PATH", os.pathsep.join([str(venv_bin), str(tools)]))
    kept = safe_spawn.child_env()["PATH"].split(os.pathsep)
    assert [os.path.normcase(os.path.realpath(p)) for p in kept] == [
        os.path.normcase(os.path.realpath(venv_bin))]


def test_a_caller_in_the_filesystem_root_keeps_the_tools_below_it(tmp_path, monkeypatch):
    # A service started in "/" or in a drive root: the root's own entry drops, and the
    # tools installed below it stay.
    from forum._vendor import safe_spawn

    root = os.path.splitdrive(str(tmp_path))[0] + os.sep if WINDOWS else os.sep
    bin_below = tmp_path / "bin"
    bin_below.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setenv("PATH", os.pathsep.join([root, str(bin_below)]))
    kept = [os.path.normcase(os.path.realpath(p))
            for p in safe_spawn.child_env()["PATH"].split(os.pathsep)]
    assert os.path.normcase(os.path.realpath(bin_below)) in kept
    assert os.path.normcase(os.path.realpath(root)) not in kept


def test_a_root_or_home_caller_keeps_the_tools_below_it(tmp_path, monkeypatch):
    # A caller in "/" or "~" narrows to that folder itself, so the entries below it
    # (npm's global folder, ~/.local/bin) stay: only the folder's own entry drops.
    from forum._vendor import safe_spawn

    home = tmp_path / "home"
    bin_below = home / ".local" / "bin"
    bin_below.mkdir(parents=True)
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(home))
    monkeypatch.chdir(home)
    monkeypatch.setenv("PATH", os.pathsep.join([str(home), str(bin_below)]))
    kept = safe_spawn.child_env()["PATH"].split(os.pathsep)
    assert os.path.normcase(str(bin_below)) in [os.path.normcase(p) for p in kept]
    assert os.path.normcase(str(home)) not in [os.path.normcase(p) for p in kept]
