from __future__ import annotations

import json
from typing import Any

from forum import __version__

SCHEMA = "project-telos.flagship-action/v1"
TOOL = "forum"
TELOS_CONTRACTS = {
    "host_surfaces": ["CLI JSON", "MCP stdio", "plugins", "IDEs", "TUIs", "apps"],
    "schemas": [
        "project-telos.flagship-action/v1",
        "project-telos.context-envelope/v1",
        "project-telos.action-receipt/v1",
        "forum.communication-contract/v1",
    ],
    "workflow_domains": ["enterprise", "research", "creative", "scientific", "education"],
    "second_brain_role": (
        "route agents, preserve ledger state, route model-foundry daemon work, "
        "shape communication contracts, and humanize outputs without adding unsupported facts"
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
                "forum.prose.contract",
                "forum.status",
                "forum.doctor",
                "forum.ledger.summary",
            ],
            "current_status": (
                "1.15.0 gate-integrity, executor isolation, daemon Origin/Host/"
                "content-type checks and a default auth token, over the 1.14 "
                "observability, auth, context budgets, capsules, delivery profiles, "
                "route frames, run rooms, runtime inspection, approval gates and "
                "campaign orchestration"
            ),
            "telos_contracts": TELOS_CONTRACTS,
        },
        next_actions=[_next("crucible", "assess", "verify the routed claim before public use")],
    )


def doctor_payload() -> dict:
    """Real readiness checks, run without a model: the roster loads, and a fresh
    ledger appends and deep-verifies. WP2 extends this to PASS/WARN/FAIL with
    executor, key-presence and state-directory checks; this release removes the
    hardcoded MATCH placeholders and the private-line route probe.
    """
    checks: list[dict[str, Any]] = [_roster_check(), _ledger_check()]
    status = "MATCH" if all(check["status"] == "MATCH" for check in checks) else "DRIFT"
    diagnostics = [
        {"code": f"{check['name']}_failed", "message": check.get("detail", "check failed")}
        for check in checks
        if check["status"] != "MATCH"
    ]
    return envelope(
        "doctor",
        status=status,
        native={"checks": checks},
        next_actions=[_next("index", "context", "refresh structural context for routing")],
        diagnostics=diagnostics,
    )


def _roster_check() -> dict[str, Any]:
    """The default roster loads and carries the full agent set."""
    try:
        from forum.roster import load_default

        count = len(load_default().agents)
    except Exception as exc:  # noqa: BLE001 - a doctor check reports, never raises
        return {"name": "default_roster", "status": "DRIFT",
                "detail": f"the default roster failed to load ({type(exc).__name__})"}
    status = "MATCH" if count > 0 else "DRIFT"
    return {"name": "default_roster", "status": status, "agents": count}


def _ledger_check() -> dict[str, Any]:
    """A fresh in-memory ledger appends and deep-verifies (the chain + payload check)."""
    try:
        from forum.ledger import InMemoryStorage, Ledger

        led = Ledger(InMemoryStorage())
        led.append(actor="doctor", kind="probe", payload={"ok": True})
        verified = led.verify(deep=True)
    except Exception as exc:  # noqa: BLE001 - a doctor check reports, never raises
        return {"name": "ledger_verification", "status": "DRIFT",
                "detail": f"the ledger check raised ({type(exc).__name__})"}
    return {"name": "ledger_verification", "status": "MATCH" if verified else "DRIFT"}


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
