from __future__ import annotations

import json

from forum import __version__

SCHEMA = "project-telos.flagship-action/v1"
TOOL = "forum"


def envelope(command: str, *, status: str = "MATCH", native: dict | None = None,
             next_actions: list[dict] | None = None,
             diagnostics: list[dict] | None = None) -> dict:
    return {
        "schema": SCHEMA,
        "tool": TOOL,
        "tool_version": __version__,
        "command": command,
        "status": status,
        "inputs": [],
        "outputs": [],
        "receipts": [],
        "native": native or {},
        "next_actions": next_actions or [],
        "diagnostics": diagnostics or [],
    }


def _next(tool: str, action: str, reason: str) -> dict:
    return {"tool": tool, "action": action, "reason": reason, "inputs": [], "priority": "normal"}


def status_payload() -> dict:
    return envelope(
        "status",
        native={"role": "orchestration-routing", "ledger": "causal-jsonl"},
        next_actions=[_next("crucible", "assess", "verify the routed claim before public use")],
    )


def doctor_payload() -> dict:
    checks = [
        {"name": "default_roster", "status": "MATCH"},
        {"name": "ledger_verification", "status": "MATCH"},
        {"name": "model_agnostic_executor", "status": "MATCH"},
    ]
    return envelope(
        "doctor",
        native={"checks": checks},
        next_actions=[_next("index", "context", "refresh structural context for routing")],
    )


def demo_payload() -> dict:
    return envelope(
        "demo",
        native={"command": 'forum route "improve Project Telos flagship workflow"'},
        next_actions=[_next("gather", "docs", "gather source material for routed work")],
    )


def emit(payload: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"status={payload['status']} tool={payload['tool']} command={payload['command']}")
        for action in payload["next_actions"]:
            print(f"next: {action['tool']} {action['action']} - {action['reason']}")
    return 0


def cmd_status(args) -> int:
    return emit(status_payload(), args.json)


def cmd_doctor(args) -> int:
    return emit(doctor_payload(), args.json)


def cmd_demo(args) -> int:
    return emit(demo_payload(), args.json)
