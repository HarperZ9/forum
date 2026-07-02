from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from forum.chat_executor import ChatExecutor
from forum.command_split import split_command
from forum.executor import Executor, SubprocessExecutor
from forum.roster import VALID_TIERS


def executors_from_runtime_config(
    path: str | os.PathLike[str],
) -> tuple[Executor | None, dict[str, Executor]]:
    """Load default and tier executors from a local runtime config file."""
    data = _load_toml(path)
    runtime = data.get("runtime", {})
    if runtime is None:
        runtime = {}
    if not isinstance(runtime, dict):
        raise ValueError("runtime must be a table")

    default = _executor_from_spec(runtime.get("default"), label="runtime.default")
    return default, _tier_executors(runtime)


def _load_toml(path: str | os.PathLike[str]) -> dict[str, Any]:
    try:
        with Path(path).open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"runtime config not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"runtime config is not valid TOML: {exc}") from exc


def _tier_executors(runtime: dict[str, Any]) -> dict[str, Executor]:
    tiers = runtime.get("tiers", {})
    if tiers is None:
        tiers = {}
    if not isinstance(tiers, dict):
        raise ValueError("runtime.tiers must be a table")

    executors = {}
    for tier, spec in tiers.items():
        if tier not in VALID_TIERS:
            raise ValueError(f"unknown runtime tier: {tier}")
        executor = _executor_from_spec(
            spec,
            label=f"runtime.tiers.{tier}",
            default_model=tier,
        )
        if executor is not None:
            executors[tier] = executor
    return executors


def _executor_from_spec(
    spec: Any,
    *,
    label: str,
    default_model: str = "default",
) -> Executor | None:
    if spec is None:
        return None
    if not isinstance(spec, dict):
        raise ValueError(f"{label} must be a table")

    chat_url = _optional_string(spec, "chat_url", label)
    cmd = _optional_string(spec, "cmd", label)
    if chat_url is not None:
        if not chat_url:
            raise ValueError(f"{label}.chat_url must not be empty")
        model = _optional_string(spec, "model", label) or default_model
        api_key_env = _optional_string(spec, "api_key_env", label)
        return ChatExecutor(model, base_url=chat_url, api_key_env=api_key_env)
    if cmd is not None:
        if not cmd:
            raise ValueError(f"{label}.cmd must not be empty")
        command = split_command(cmd)
        if not command:
            raise ValueError(f"{label}.cmd must include a command")
        return SubprocessExecutor(command)
    return None


def _optional_string(spec: dict[str, Any], key: str, label: str) -> str | None:
    value = spec.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label}.{key} must be a string")
    return value
