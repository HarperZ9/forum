"""A --runtime-config command honors the same launch variables as --cmd.

Falsifier for review finding F8. On the first 1.15.0 candidate FORUM_ALLOW_EXEC_CLI
and FORUM_CHILD_ENV reached a child started by --cmd, but a command named in a
runtime config file was built without them: a granted CLI was refused and a named
variable never reached the child. Local stand-ins only.
"""
import asyncio
import json

import pytest
from executor_stand_in import make_world, stand_in

from forum.executor import Assignment
from forum.runtime_config import executors_from_runtime_config


@pytest.fixture
def world(tmp_path, monkeypatch):
    return make_world(tmp_path, monkeypatch)


def _config(world, body):
    path = world["tmp"] / "runtime.toml"
    path.write_text(body, encoding="utf-8")
    return str(path)


def _run(executor):
    return asyncio.run(executor.run(Assignment("T1", "worker", "hi")))


def test_a_runtime_config_command_honors_the_launch_grants(world, monkeypatch):
    record = str(world["tmp"] / "gemini.json")
    stand_in(str(world["bin"]), "gemini", record)
    monkeypatch.setenv("FORUM_ALLOW_EXEC_CLI", "gemini")
    monkeypatch.setenv("FORUM_CHILD_ENV", "HTTPS_PROXY")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    default, _ = executors_from_runtime_config(_config(world, '[runtime.default]\ncmd = "gemini"\n'))
    result = _run(default)
    assert result.ok is True, result.output
    with open(record, encoding="utf-8") as fh:
        env = {k.upper(): v for k, v in json.load(fh)["env"].items()}
    assert env.get("HTTPS_PROXY") == "http://proxy.invalid:3128"


def test_a_runtime_config_tier_command_honors_the_launch_grants(world, monkeypatch):
    record = str(world["tmp"] / "gemini.json")
    stand_in(str(world["bin"]), "gemini", record)
    monkeypatch.setenv("FORUM_ALLOW_EXEC_CLI", "gemini")
    _, tiers = executors_from_runtime_config(
        _config(world, '[runtime.tiers.cheap]\ncmd = "gemini"\n'))
    assert _run(tiers["cheap"]).ok is True


def test_a_runtime_config_command_is_refused_without_the_grant(world):
    record = str(world["tmp"] / "gemini.json")
    stand_in(str(world["bin"]), "gemini", record)
    default, _ = executors_from_runtime_config(_config(world, '[runtime.default]\ncmd = "gemini"\n'))
    result = _run(default)
    assert result.ok is False
    assert "GRANT_REQUIRED" in result.output
