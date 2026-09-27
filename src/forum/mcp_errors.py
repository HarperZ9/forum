"""Closed tool errors for the MCP surface, and the gate-decision launch grant.

A tool failure returns ``isError: true`` with ``structuredContent`` of the form
``{"code", "retryable", "setup", "detail"}`` and the same JSON in a text block for
clients that read only text. The detail is a fixed sentence per case: it never
carries a path, an environment value or upstream text.
"""
from __future__ import annotations

import json

# The tools that decide what a paused run does. A model connected over MCP gets
# them only when the person who launched the server passed the grant.
GATE_WRITE_TOOLS = frozenset({"gate_approve", "gate_edit", "gate_reject"})
GATE_GRANT_SETUP = "ALLOW_GATE_DECISIONS"
GATE_GRANT_DETAIL = (
    "gate decisions over MCP need the --allow-gate-decisions launch grant; "
    "a person can decide with `forum gate approve|edit|reject` instead"
)


def tool_error(code: str, detail: str, *, setup: str | None = None, retryable: bool = False) -> dict:
    """A tools/call result for a refused or failed call, in the closed error shape."""
    body = {"code": code, "retryable": retryable, "setup": setup, "detail": detail}
    return {
        "content": [{"type": "text", "text": json.dumps(body)}],
        "structuredContent": body,
        "isError": True,
    }


def gate_grant_required() -> dict:
    """The result for a gate decision tool called without the launch grant."""
    return tool_error("GRANT_REQUIRED", GATE_GRANT_DETAIL, setup=GATE_GRANT_SETUP)


# A failed gate decision, by the code the shared HTTP handler reports. Each
# detail is fixed text: nothing from the request or the ledger is echoed.
_GATE_DECISION_DETAILS = {
    "NOT_FOUND": "no gate is pending for that run_seq and wave; gate_list shows the open gates",
    "INVALID_ARGUMENT": "the decision's arguments are invalid: run_seq and wave are integers, "
                        "approver is a non-empty string, and an edit names only tasks of the gated wave",
}


def gate_decision_error(status: int, body: bytes) -> dict:
    """The closed error for a gate decision the HTTP handler refused with ``status``."""
    try:
        code = json.loads(body.decode("utf-8")).get("code")
    except (ValueError, UnicodeDecodeError, AttributeError):
        code = None
    if code not in _GATE_DECISION_DETAILS:
        code = "INVALID_ARGUMENT" if 400 <= status < 500 else "INTERNAL"
    detail = _GATE_DECISION_DETAILS.get(code, "the gate decision failed on the server")
    return tool_error(code, detail)
