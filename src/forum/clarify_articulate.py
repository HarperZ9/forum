"""Hand a clarify rewrite to Articulate's deterministic fix and meaning guard.

Two routes, tried in order:

1. ``python``: the ``articulate`` package (PyPI ``articulate-writing``) imports in
   this interpreter. Forum calls ``host_edit.deterministic_edit`` on its candidate,
   then ``edit_plan``/``edit_submit`` so Articulate's guard compares the result
   with the original text and issues its editor receipt.
2. ``cli``: the ``articulate`` command resolves through the vendored
   ``safe_spawn`` helper (``FORUM_ARTICULATE_CLI`` may hold its full path). The
   same three steps run as ``articulate plan``, ``articulate fix --backend none``
   and ``articulate submit``, each in a new private folder with a stripped
   environment and ``ARTICULATE_LOCAL_ONLY=1``.

Neither route selects a model backend, so neither calls a model or the network.
Any failure raises ArticulateUnavailable and the caller falls back to Forum's
fixed rules.
"""
from __future__ import annotations

import importlib
import json
import logging
import subprocess
from collections.abc import Callable
from typing import Any

from forum._vendor import safe_spawn

ARTICULATE_PROFILE = "flavored"
CLI_NAME = "articulate"
CLI_OVERRIDE_VAR = "FORUM_ARTICULATE_CLI"
CLI_TIMEOUT_S = 30
_LOG = logging.getLogger(__name__)

Runner = Callable[..., subprocess.CompletedProcess]


class ArticulateUnavailable(RuntimeError):
    """Articulate could not be used; the message names the reason, never a path."""


def hand_off(original: str, candidate: str, *, runner: Runner | None = None) -> dict:
    """Articulate's guarded result for `candidate` as a rewrite of `original`."""
    try:
        host_edit = importlib.import_module("articulate.host_edit")
        version = str(getattr(importlib.import_module("articulate"), "__version__", "unknown"))
    except ImportError:
        return _via_cli(original, candidate, runner or safe_spawn.run)
    try:
        fixed = host_edit.deterministic_edit(candidate, profile=ARTICULATE_PROFILE)["text"]
        plan = host_edit.edit_plan(original, goal="fix", profile=ARTICULATE_PROFILE)
        result = host_edit.edit_submit(original, fixed, plan["plan_id"])
    except Exception as exc:  # an incompatible Articulate release must not break clarify
        _LOG.warning("articulate python route failed: %s", type(exc).__name__)
        raise ArticulateUnavailable(f"articulate python route failed ({type(exc).__name__})") from exc
    return _summarize(result, route="python", version=version)


def _via_cli(original: str, candidate: str, runner: Runner) -> dict:
    fixed = _cli_json(runner, ["fix", "candidate.txt", "--profile", ARTICULATE_PROFILE,
                               "--backend", "none", "--json"], {"candidate.txt": candidate})["text"]
    plan = _cli_json(runner, ["plan", "original.txt", "--goal", "fix", "--profile",
                              ARTICULATE_PROFILE], {"original.txt": original})
    result = _cli_json(runner, ["submit", "original.txt", "rewrite.txt", "--plan", plan["plan_id"]],
                       {"original.txt": original, "rewrite.txt": fixed})
    return _summarize(result, route="cli", version=_cli_version(result))


def _cli_json(runner: Runner, args: list[str], files: dict[str, str]) -> dict:
    def argv(paths: dict[str, str]) -> list[str]:
        return [paths.get(a, a) for a in args]

    try:
        proc = runner(CLI_NAME, argv, override_var=CLI_OVERRIDE_VAR, files=files,
                      timeout=CLI_TIMEOUT_S, set_env={"ARTICULATE_LOCAL_ONLY": "1"})
    except safe_spawn.SpawnRefused as exc:
        raise ArticulateUnavailable(f"articulate CLI not usable ({exc.code})") from exc
    except subprocess.TimeoutExpired as exc:
        raise ArticulateUnavailable("articulate CLI timed out") from exc
    if proc.returncode != 0:
        _LOG.warning("articulate %s exited %s", args[0], proc.returncode)
        raise ArticulateUnavailable(f"articulate {args[0]} exited {proc.returncode}")
    try:
        data = json.loads(proc.stdout or "")
    except ValueError as exc:
        raise ArticulateUnavailable(f"articulate {args[0]} did not return JSON") from exc
    if not isinstance(data, dict) or not data.get("ok", False):
        raise ArticulateUnavailable(f"articulate {args[0]} did not report ok")
    return data


def _cli_version(result: dict) -> str:
    receipt = result.get("receipt")
    settings = receipt.get("settings") if isinstance(receipt, dict) else None
    ruleset = settings.get("ruleset") if isinstance(settings, dict) else None
    return f"cli (ruleset {ruleset})" if ruleset else "cli"


def _summarize(result: dict[str, Any], *, route: str, version: str) -> dict:
    text = result.get("text")
    if not isinstance(text, str):
        raise ArticulateUnavailable("articulate returned no text")
    remaining = result.get("remaining_findings") or []
    return {
        "text": text,
        "route": route,
        "version": version,
        "profile": ARTICULATE_PROFILE,
        "gate_before": result.get("gate_before"),
        "gate_after": result.get("gate_after"),
        "refused": result.get("refused", []),
        "remaining_rule_ids": sorted({f.get("rule_id", "") for f in remaining if isinstance(f, dict)}),
        "receipt": result.get("receipt"),
    }
