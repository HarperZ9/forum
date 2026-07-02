from __future__ import annotations

from forum.context_budget import (
    ContextBudget,
    ContextBudgetMeter,
    apply_context_budget,
    approx_tokens,
)

CONTEXT_PREFLIGHT_SCHEMA = "forum.context-preflight/v1"


def build_context_preflight(
    request: str,
    *,
    context: str = "",
    context_source: str = "none",
    budget: ContextBudget | None = None,
) -> dict:
    context_payload, issues = _context_payload(context, context_source, budget)
    return {
        "schema": CONTEXT_PREFLIGHT_SCHEMA,
        "ready": context_payload["action"] != "omitted",
        "request": {
            "bytes": len(request.encode("utf-8")),
            "tokens": approx_tokens(
                request,
                budget.bytes_per_token if budget is not None else 4,
            ),
        },
        "context": context_payload,
        "limits": budget.configured_limits() if budget is not None else {},
        "issues": issues,
    }


def context_preflight_text(payload: dict) -> str:
    request = payload.get("request") or {}
    context = payload.get("context") or {}
    lines = [
        "Forum context preflight",
        f"ready: {payload.get('ready', False)}",
        f"request: {request.get('tokens', 0)} tokens",
        (
            "context: "
            f"{context.get('source', 'none')} "
            f"{context.get('action', 'none')} "
            f"{context.get('original_tokens', 0)}->"
            f"{context.get('admitted_tokens', 0)} tokens"
        ),
    ]
    limits = payload.get("limits") or {}
    if limits:
        ordered = " ".join(f"{key}={limits[key]}" for key in sorted(limits))
        lines.append(f"limits: {ordered}")
    issues = payload.get("issues") or []
    if issues:
        lines.append("issues:")
        lines.extend(f"- {issue}" for issue in issues)
    return "\n".join(lines)


def _context_payload(
    context: str,
    context_source: str,
    budget: ContextBudget | None,
) -> tuple[dict, list[str]]:
    if not context:
        return _empty_context(), []
    if budget is None:
        tokens = approx_tokens(context)
        return {
            "source": context_source,
            "action": "retained",
            "reason": "no_budget",
            "original_tokens": tokens,
            "admitted_tokens": tokens,
            "tokens_saved": 0,
        }, []

    meter = ContextBudgetMeter()
    _, pressure = apply_context_budget("request", context_source, context, budget, meter)
    tokens_saved = pressure.original_tokens - pressure.admitted_tokens
    payload = {
        "source": context_source,
        "action": pressure.action,
        "reason": pressure.reason,
        "original_tokens": pressure.original_tokens,
        "admitted_tokens": pressure.admitted_tokens,
        "tokens_saved": tokens_saved,
    }
    return payload, _issues(context_source, pressure.action)


def _empty_context() -> dict:
    return {
        "source": "none",
        "action": "none",
        "reason": "no_context",
        "original_tokens": 0,
        "admitted_tokens": 0,
        "tokens_saved": 0,
    }


def _issues(context_source: str, action: str) -> list[str]:
    if action == "trimmed":
        return [f"{context_source} context would be trimmed before planning"]
    if action == "omitted":
        return [f"{context_source} context would be omitted before planning"]
    return []
