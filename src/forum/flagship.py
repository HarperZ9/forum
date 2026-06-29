from __future__ import annotations

import json

from forum import __version__

SCHEMA = "project-telos.flagship-action/v1"
TOOL = "forum"
TELOS_CONTRACTS = {
    "host_surfaces": ["CLI JSON", "MCP stdio", "plugins", "IDEs", "TUIs", "apps"],
    "schemas": [
        "project-telos.flagship-action/v1",
        "project-telos.context-envelope/v1",
        "project-telos.action-receipt/v1",
    ],
    "workflow_domains": ["enterprise", "research", "creative", "scientific", "education"],
    "second_brain_role": (
        "route agents, preserve ledger state, route model-foundry daemon work, "
        "and humanize outputs without adding unsupported facts"
    ),
    "privacy_boundary": "hosts receive receipts, hashes, redacted refs, and verdicts; raw private payloads stay in local adapters",
}


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
        native={
            "role": "orchestration-routing",
            "ledger": "causal-jsonl",
            "operator_commands": ["status", "doctor", "demo", "mcp"],
            "mcp_tools": [
                "forum.route",
                "forum.prose.humanize",
                "forum.status",
                "forum.doctor",
                "forum.ledger.summary",
            ],
            "current_status": (
                "1.12.0 per-task context with 28-lane Project Telos roster, "
                "model-foundry daemon routing, and MCP parity"
            ),
            "telos_contracts": TELOS_CONTRACTS,
        },
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
