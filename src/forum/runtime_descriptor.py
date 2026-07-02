from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forum.command_split import split_command
from forum.executor import executor_id
from forum.roster import VALID_TIERS


@dataclass(frozen=True, slots=True)
class RuntimeExecutorSpec:
    kind: str
    identity: str
    source: str
    detail: dict[str, str]

    def payload(self) -> dict:
        return {
            "kind": self.kind,
            "id": self.identity,
            "source": self.source,
            "detail": dict(self.detail),
        }


def descriptor_from_config(
    path: str | os.PathLike[str],
) -> tuple[RuntimeExecutorSpec | None, dict[str, RuntimeExecutorSpec]]:
    data = _load_toml(path)
    runtime = data.get("runtime", {})
    if runtime is None:
        runtime = {}
    if not isinstance(runtime, dict):
        raise ValueError("runtime must be a table")

    default = _descriptor_from_spec(
        runtime.get("default"),
        label="runtime.default",
        source="config",
    )
    return default, _tier_descriptors(runtime)


def cli_default_descriptor(args) -> RuntimeExecutorSpec | None:
    chat_url = getattr(args, "chat_url", None)
    if chat_url:
        model = getattr(args, "model", None) or "default"
        detail = {"base_url": chat_url, "model": model}
        api_key_env = getattr(args, "api_key_env", None)
        if api_key_env:
            detail["api_key_env"] = api_key_env
        return RuntimeExecutorSpec("chat", model, "cli", detail)
    if getattr(args, "api", False):
        model = getattr(args, "model", None) or "claude-sonnet-4-6"
        return RuntimeExecutorSpec(
            "api",
            model,
            "cli",
            {
                "provider": "anthropic",
                "model": model,
                "api_key_env": "ANTHROPIC_API_KEY",
            },
        )
    cmd = getattr(args, "cmd", None)
    if cmd:
        return _command_descriptor(cmd, source="cli")
    return None


def cli_tier_descriptors(args) -> dict[str, RuntimeExecutorSpec]:
    specs = {}
    for tier in ("cheap", "capable", "frontier"):
        chat_url = getattr(args, f"{tier}_chat_url", None)
        cmd = getattr(args, f"{tier}_cmd", None)
        if chat_url:
            model = getattr(args, f"{tier}_model", None) or tier
            detail = {"base_url": chat_url, "model": model}
            api_key_env = getattr(args, f"{tier}_api_key_env", None)
            if api_key_env:
                detail["api_key_env"] = api_key_env
            specs[tier] = RuntimeExecutorSpec("chat", model, "cli", detail)
        elif cmd:
            specs[tier] = _command_descriptor(cmd, source="cli")
    return specs


def descriptors_from_executor(
    executor: Any,
) -> tuple[RuntimeExecutorSpec | None, dict[str, RuntimeExecutorSpec]]:
    """Describe the live executor graph without running it."""
    if executor is None:
        return None, {}
    default = getattr(executor, "_default", None)
    tiers = getattr(executor, "_tiers", None)
    if getattr(executor, "model_id", None) == "tiered" and default is not None and isinstance(tiers, dict):
        tier_descriptors = {}
        for tier, tier_executor in tiers.items():
            if tier not in VALID_TIERS:
                continue
            descriptor = _live_descriptor(tier_executor)
            if descriptor is not None:
                tier_descriptors[tier] = descriptor
        return _live_descriptor(default), tier_descriptors
    return _live_descriptor(executor), {}


def _load_toml(path: str | os.PathLike[str]) -> dict[str, Any]:
    try:
        with Path(path).open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"runtime config not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"runtime config is not valid TOML: {exc}") from exc


def _tier_descriptors(runtime: dict[str, Any]) -> dict[str, RuntimeExecutorSpec]:
    tiers = runtime.get("tiers", {})
    if tiers is None:
        tiers = {}
    if not isinstance(tiers, dict):
        raise ValueError("runtime.tiers must be a table")

    descriptors = {}
    for tier, spec in tiers.items():
        if tier not in VALID_TIERS:
            raise ValueError(f"unknown runtime tier: {tier}")
        descriptor = _descriptor_from_spec(
            spec,
            label=f"runtime.tiers.{tier}",
            source="config",
            default_model=tier,
        )
        if descriptor is not None:
            descriptors[tier] = descriptor
    return descriptors


def _descriptor_from_spec(
    spec: Any,
    *,
    label: str,
    source: str,
    default_model: str = "default",
) -> RuntimeExecutorSpec | None:
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
        detail = {"base_url": chat_url, "model": model}
        api_key_env = _optional_string(spec, "api_key_env", label)
        if api_key_env:
            detail["api_key_env"] = api_key_env
        return RuntimeExecutorSpec("chat", model, source, detail)
    if cmd is not None:
        if not cmd:
            raise ValueError(f"{label}.cmd must not be empty")
        return _command_descriptor(cmd, source=source)
    return None


def _command_descriptor(cmd: str, *, source: str) -> RuntimeExecutorSpec:
    argv = split_command(cmd)
    if not argv:
        raise ValueError("runtime command must include a command")
    return RuntimeExecutorSpec(
        "cmd",
        "SubprocessExecutor",
        source,
        {"argv": " ".join(argv)},
    )


def _live_descriptor(executor: Any) -> RuntimeExecutorSpec | None:
    if executor is None:
        return None
    type_name = type(executor).__name__
    if type_name == "ChatExecutor":
        model = str(getattr(executor, "_model", executor_id(executor)))
        detail = {
            "base_url": str(getattr(executor, "_base_url", "")),
            "model": model,
        }
        api_key_env = getattr(executor, "_api_key_env", None)
        if api_key_env:
            detail["api_key_env"] = str(api_key_env)
        return RuntimeExecutorSpec("chat", model, "current", detail)
    if type_name == "ApiExecutor":
        model = str(getattr(executor, "_model", executor_id(executor)))
        return RuntimeExecutorSpec(
            "api",
            model,
            "current",
            {
                "provider": "anthropic",
                "model": model,
                "api_key_env": str(getattr(executor, "_api_key_env", "ANTHROPIC_API_KEY")),
            },
        )
    if type_name == "SubprocessExecutor":
        command = [str(part) for part in getattr(executor, "_command", [])]
        return RuntimeExecutorSpec("cmd", "SubprocessExecutor", "current", {"argv": " ".join(command)})
    return RuntimeExecutorSpec(
        "executor",
        str(executor_id(executor)),
        "current",
        {"type": type_name},
    )


def _optional_string(spec: dict[str, Any], key: str, label: str) -> str | None:
    value = spec.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label}.{key} must be a string")
    return value
