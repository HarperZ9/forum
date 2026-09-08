#!/usr/bin/env python3
"""Read-only Forum route/context/runtime/prose preflight helper."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PATH_VALUE_FLAGS = {"--ledger", "--runtime-config"}
COMMAND_VALUE_FLAGS = {"--cmd", "--cheap-cmd", "--capable-cmd", "--frontier-cmd"}
URL_VALUE_FLAGS = {
    "--chat-url",
    "--cheap-chat-url",
    "--capable-chat-url",
    "--frontier-chat-url",
}
MODEL_VALUE_FLAGS = {"--model", "--cheap-model", "--capable-model", "--frontier-model"}
ENV_VALUE_FLAGS = {
    "--api-key-env",
    "--cheap-api-key-env",
    "--capable-api-key-env",
    "--frontier-api-key-env",
}
REDACTED_VALUE_BY_FLAG = {
    **{flag: "<path>" for flag in PATH_VALUE_FLAGS},
    **{flag: "<runtime-command>" for flag in COMMAND_VALUE_FLAGS},
    **{flag: "<chat-url>" for flag in URL_VALUE_FLAGS},
    **{flag: "<model>" for flag in MODEL_VALUE_FLAGS},
    **{flag: "<api-key-env>" for flag in ENV_VALUE_FLAGS},
}


class ReceiptPrivacy:
    def __init__(
        self,
        *,
        task_text: str,
        paths: list[str] | None = None,
        commands: list[str] | None = None,
        chat_urls: list[str] | None = None,
        models: list[str] | None = None,
        api_key_env_names: list[str] | None = None,
    ) -> None:
        self.task_text = task_text
        self.replacements: list[tuple[str, str]] = []
        self._add(task_text, "<task-text>")
        for value in paths or []:
            self._add(value, "<path>")
        for value in commands or []:
            self._add(value, "<runtime-command>")
        for value in chat_urls or []:
            self._add(value, "<chat-url>")
        for value in models or []:
            self._add(value, "<model>")
        for value in api_key_env_names or []:
            self._add(value, "<api-key-env>")
            env_value = os.environ.get(value)
            if env_value:
                self._add(env_value, "<api-key-value>")
        self.replacements.sort(key=lambda item: len(item[0]), reverse=True)

    def _add(self, value: str | None, placeholder: str) -> None:
        if value:
            self.replacements.append((value, placeholder))

    def scrub_string(self, value: str) -> str:
        out = value
        for secret, placeholder in self.replacements:
            out = out.replace(secret, placeholder)
        return out

    def scrub_json(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.scrub_string(value)
        if isinstance(value, list):
            return [self.scrub_json(item) for item in value]
        if isinstance(value, dict):
            return {key: self.scrub_json(item) for key, item in value.items()}
        return value

    def command(self, args: list[str]) -> list[str]:
        out = ["python", "-m", "forum"]
        redacted_next: str | None = None
        for item in args:
            if redacted_next is not None:
                out.append(redacted_next)
                redacted_next = None
                continue
            placeholder = REDACTED_VALUE_BY_FLAG.get(item)
            if placeholder is not None:
                out.append(item)
                redacted_next = placeholder
            elif item == self.task_text:
                out.append("<task-text>")
            else:
                out.append(self.scrub_string(item))
        return out


def _env(source_src: str | None) -> dict[str, str]:
    env = os.environ.copy()
    if source_src:
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = source_src if not existing else source_src + os.pathsep + existing
    return env


def _validate_forum_source(raw: str | None) -> tuple[dict[str, Any], str | None, str | None]:
    if not raw:
        return {"kind": "installed-package", "ready": True}, None, None
    try:
        root = Path(raw).expanduser().resolve(strict=False)
    except OSError:
        return {
            "kind": "source-checkout",
            "ready": False,
            "error": "invalid_forum_repo",
            "message": "--forum-repo could not be resolved",
        }, None, None
    src = root / "src"
    package = src / "forum"
    if not root.is_dir() or not package.is_dir():
        return {
            "kind": "source-checkout",
            "ready": False,
            "error": "invalid_forum_repo",
            "message": "--forum-repo must point to a Forum source checkout containing src/forum",
        }, None, None
    return {"kind": "source-checkout", "ready": True}, str(root), str(src)


def _stream_digest(data: bytes) -> dict[str, Any]:
    return {
        "byte_count": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _diagnostics(stdout: bytes, stderr: bytes) -> dict[str, Any]:
    return {
        "stdout": _stream_digest(stdout),
        "stderr": _stream_digest(stderr),
    }


def _json_error(exc: BaseException) -> dict[str, Any]:
    out: dict[str, Any] = {"type": exc.__class__.__name__}
    if isinstance(exc, json.JSONDecodeError):
        out.update({"line": exc.lineno, "column": exc.colno, "position": exc.pos})
    return out


def _run_json(
    args: list[str],
    *,
    source_root: str | None,
    source_src: str | None,
    privacy: ReceiptPrivacy,
) -> dict[str, Any]:
    command = [sys.executable, "-m", "forum", *args]
    try:
        proc = subprocess.run(
            command,
            cwd=source_root,
            env=_env(source_src),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as exc:
        return {
            "error": "forum_command_start_failed",
            "command": privacy.command(args),
            "exception_type": exc.__class__.__name__,
        }
    if proc.returncode != 0:
        return {
            "error": "forum_command_failed",
            "command": privacy.command(args),
            "exit_code": proc.returncode,
            "diagnostics": _diagnostics(proc.stdout, proc.stderr),
        }
    try:
        return privacy.scrub_json(json.loads(proc.stdout))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {
            "error": "forum_json_parse_failed",
            "command": privacy.command(args),
            "exit_code": proc.returncode,
            "json_error": _json_error(exc),
            "diagnostics": _diagnostics(proc.stdout, proc.stderr),
        }


def _contract(text: str, *, profile: str | None, source_src: str | None) -> dict[str, Any]:
    if source_src:
        sys.path.insert(0, source_src)
    try:
        from forum.communication_contract import build_communication_contract
        from forum.roster import load_default
        from forum.route_frame import derive_route_frame
        from forum.routing import LexicalRouter
    except Exception as exc:  # pragma: no cover - host diagnostic path
        return {"error": "forum_import_failed", "exception_type": exc.__class__.__name__}
    roster = load_default()
    result = LexicalRouter().score(text, roster)
    frame = derive_route_frame(text, result, roster)
    try:
        return build_communication_contract(
            domain=frame.domain,
            intent=frame.intent,
            posture=frame.posture,
            profile=profile or frame.delivery_profile,
            human_contract=frame.human_contract,
            proof_lane=frame.proof_lane,
            domain_lane=frame.domain_lane,
        )
    except ValueError as exc:
        return {"error": "contract_failed", "exception_type": exc.__class__.__name__}


def _preflight_args(args: argparse.Namespace) -> list[str]:
    out = ["context", "preflight", "--json"]
    if args.use_capsule_context:
        out.append("--use-capsule-context")
    if args.ledger:
        out.extend(["--ledger", args.ledger])
    if args.context_token_budget is not None:
        out.extend(["--context-token-budget", str(args.context_token_budget)])
    if args.request_context_token_budget is not None:
        out.extend(["--request-context-token-budget", str(args.request_context_token_budget)])
    if args.task_context_token_budget is not None:
        out.extend(["--task-context-token-budget", str(args.task_context_token_budget)])
    if args.upstream_token_budget is not None:
        out.extend(["--upstream-token-budget", str(args.upstream_token_budget)])
    if args.max_items is not None:
        out.extend(["--max-items", str(args.max_items)])
    if args.max_text_chars is not None:
        out.extend(["--max-text-chars", str(args.max_text_chars)])
    out.append(args.text)
    return out


def _runtime_args(args: argparse.Namespace) -> list[str]:
    out = ["runtime", "inspect", "--json"]
    for flag, attr in [
        ("--runtime-config", "runtime_config"),
        ("--cmd", "cmd"),
        ("--cheap-cmd", "cheap_cmd"),
        ("--capable-cmd", "capable_cmd"),
        ("--frontier-cmd", "frontier_cmd"),
        ("--chat-url", "chat_url"),
        ("--cheap-chat-url", "cheap_chat_url"),
        ("--capable-chat-url", "capable_chat_url"),
        ("--frontier-chat-url", "frontier_chat_url"),
        ("--model", "model"),
        ("--cheap-model", "cheap_model"),
        ("--capable-model", "capable_model"),
        ("--frontier-model", "frontier_model"),
        ("--api-key-env", "api_key_env"),
        ("--cheap-api-key-env", "cheap_api_key_env"),
        ("--capable-api-key-env", "capable_api_key_env"),
        ("--frontier-api-key-env", "frontier_api_key_env"),
    ]:
        value = getattr(args, attr)
        if value:
            out.extend([flag, value])
    if args.api:
        out.append("--api")
    return out


def _section_error(section: dict[str, Any]) -> str | None:
    value = section.get("error")
    return value if isinstance(value, str) else None


def _status(route: dict[str, Any], preflight: dict[str, Any], runtime: dict[str, Any], contract: dict[str, Any]) -> str:
    if any(_section_error(section) for section in (route, preflight, runtime, contract)):
        return "UNVERIFIABLE"
    if route.get("needs_escalation") or not route.get("decided"):
        return "PREFLIGHT_BLOCKED"
    if preflight.get("ready") is False or runtime.get("ready") is False:
        return "PREFLIGHT_BLOCKED"
    return "PREFLIGHT_RECORDED"


def _decision(route: dict[str, Any], preflight: dict[str, Any], runtime: dict[str, Any], manual: str | None) -> dict[str, Any]:
    reasons: list[str] = []
    for section, reason in [
        (route, "route_unverifiable"),
        (preflight, "context_preflight_unverifiable"),
        (runtime, "runtime_inspection_unverifiable"),
    ]:
        if _section_error(section) == "invalid_forum_repo" and "invalid_forum_repo" not in reasons:
            reasons.append("invalid_forum_repo")
        elif _section_error(section):
            reasons.append(reason)
    decided = route.get("decided")
    if not _section_error(route) and (route.get("needs_escalation") or not decided):
        reasons.append("route_needs_escalation")
    if manual and decided and manual != decided:
        reasons.append("manual_lane_disagrees_with_route")
    if preflight.get("ready") is False:
        reasons.append("context_not_ready")
    if runtime.get("ready") is False:
        reasons.append("runtime_executor_missing")
    return {
        "safe_to_submit": False,
        "reason": reasons or ["preflight_only_no_execution_authority"],
        "manual_lane": manual,
        "route_lane": decided,
    }


def _invalid_source_section() -> dict[str, Any]:
    return {
        "error": "invalid_forum_repo",
        "message": "Forum source checkout unavailable; no Forum command was run",
    }


def _build_payload(
    *,
    source_info: dict[str, Any],
    task_hash: str,
    route: dict[str, Any],
    preflight: dict[str, Any],
    runtime: dict[str, Any],
    contract: dict[str, Any],
    manual_lane: str | None,
) -> dict[str, Any]:
    payload = {
        "schema": "forum-route-preflight.receipt/v2",
        "status": _status(route, preflight, runtime, contract),
        "forum_source": source_info,
        "task_text_sha256": task_hash,
        "task_text_included": False,
        "route": route,
        "context_preflight": preflight,
        "runtime": runtime,
        "communication_contract": contract,
        "decision": _decision(route, preflight, runtime, manual_lane),
        "does_not_prove": [
            "the route is semantically correct",
            "a model executor is configured unless runtime.ready is true",
            "any work was dispatched or completed",
            "Forum exposes one executable tool per roster lane",
        ],
    }
    return payload


def _values(args: argparse.Namespace, names: list[str]) -> list[str]:
    return [value for name in names if (value := getattr(args, name))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("text", help="task or unfinished-work request to preflight")
    parser.add_argument("--forum-repo", help="Forum source checkout; its src/ is added before imports")
    parser.add_argument("--manual-lane", help="user-stated or manually selected expected Forum lane")
    parser.add_argument("--profile", help="optional prose contract profile override")
    parser.add_argument("--ledger", help="Forum ledger directory for capsule context")
    parser.add_argument("--use-capsule-context", action="store_true")
    parser.add_argument("--max-items", type=int)
    parser.add_argument("--max-text-chars", type=int)
    parser.add_argument("--context-token-budget", type=int)
    parser.add_argument("--request-context-token-budget", type=int)
    parser.add_argument("--task-context-token-budget", type=int)
    parser.add_argument("--upstream-token-budget", type=int)
    parser.add_argument("--runtime-config", help="pass through to forum runtime inspect without executing a model")
    parser.add_argument("--cmd", help="pass through to forum runtime inspect without executing a model")
    parser.add_argument("--cheap-cmd", help="pass through to forum runtime inspect without executing a model")
    parser.add_argument("--capable-cmd", help="pass through to forum runtime inspect without executing a model")
    parser.add_argument("--frontier-cmd", help="pass through to forum runtime inspect without executing a model")
    parser.add_argument("--chat-url", help="pass through to forum runtime inspect")
    parser.add_argument("--cheap-chat-url", help="pass through to forum runtime inspect")
    parser.add_argument("--capable-chat-url", help="pass through to forum runtime inspect")
    parser.add_argument("--frontier-chat-url", help="pass through to forum runtime inspect")
    parser.add_argument("--model", help="pass through to forum runtime inspect")
    parser.add_argument("--cheap-model", help="pass through to forum runtime inspect")
    parser.add_argument("--capable-model", help="pass through to forum runtime inspect")
    parser.add_argument("--frontier-model", help="pass through to forum runtime inspect")
    parser.add_argument("--api-key-env", help="pass through to forum runtime inspect")
    parser.add_argument("--cheap-api-key-env", help="pass through to forum runtime inspect")
    parser.add_argument("--capable-api-key-env", help="pass through to forum runtime inspect")
    parser.add_argument("--frontier-api-key-env", help="pass through to forum runtime inspect")
    parser.add_argument("--api", action="store_true", help="pass through to forum runtime inspect")
    args = parser.parse_args()

    task_hash = hashlib.sha256(args.text.encode("utf-8")).hexdigest()
    source_info, source_root, source_src = _validate_forum_source(args.forum_repo)
    privacy = ReceiptPrivacy(
        task_text=args.text,
        paths=[args.forum_repo or "", source_root or "", source_src or "", args.ledger or "", args.runtime_config or ""],
        commands=_values(args, ["cmd", "cheap_cmd", "capable_cmd", "frontier_cmd"]),
        chat_urls=_values(args, ["chat_url", "cheap_chat_url", "capable_chat_url", "frontier_chat_url"]),
        models=_values(args, ["model", "cheap_model", "capable_model", "frontier_model"]),
        api_key_env_names=_values(args, ["api_key_env", "cheap_api_key_env", "capable_api_key_env", "frontier_api_key_env"]),
    )

    if source_info.get("error") == "invalid_forum_repo":
        section = _invalid_source_section()
        payload = _build_payload(
            source_info=source_info,
            task_hash=task_hash,
            route=section,
            preflight=section,
            runtime=section,
            contract=section,
            manual_lane=args.manual_lane,
        )
        print(json.dumps(payload, indent=2))
        return 0

    route = _run_json(["route", "--json", args.text], source_root=source_root, source_src=source_src, privacy=privacy)
    preflight = _run_json(_preflight_args(args), source_root=source_root, source_src=source_src, privacy=privacy)
    runtime = _run_json(_runtime_args(args), source_root=source_root, source_src=source_src, privacy=privacy)
    contract = _contract(args.text, profile=args.profile, source_src=source_src)
    payload = _build_payload(
        source_info=source_info,
        task_hash=task_hash,
        route=route,
        preflight=preflight,
        runtime=runtime,
        contract=contract,
        manual_lane=args.manual_lane,
    )
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
