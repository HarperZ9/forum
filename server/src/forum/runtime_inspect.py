from __future__ import annotations

from collections import Counter

from forum.roster import VALID_TIERS, Roster
from forum.runtime_descriptor import RuntimeExecutorSpec

RUNTIME_INSPECT_SCHEMA = "forum.runtime.inspect/v1"


def inspect_runtime(
    default: RuntimeExecutorSpec | None,
    tiers: dict[str, RuntimeExecutorSpec],
    roster: Roster,
) -> dict:
    roster_tiers = _roster_tiers(roster)
    default_payload = _executor_payload(default)
    tier_payloads = {}
    issues = []
    if default is None:
        issues.append("no default executor configured for control roles")

    for tier in sorted(VALID_TIERS):
        if tier in tiers:
            tier_payloads[tier] = tiers[tier].payload()
        elif default is not None:
            tier_payloads[tier] = {
                "kind": "fallback",
                "id": default.identity,
                "source": "default",
                "detail": {"tier": tier},
            }
        else:
            tier_payloads[tier] = _missing_payload()
            if roster_tiers.get(tier, 0) > 0:
                issues.append(f"no executor configured for roster tier: {tier}")

    return {
        "schema": RUNTIME_INSPECT_SCHEMA,
        "ready": not issues,
        "default": default_payload,
        "tiers": tier_payloads,
        "roster": {"agents": len(roster.agents), "tiers": roster_tiers},
        "issues": issues,
    }


def runtime_inspect_text(payload: dict) -> str:
    lines = [
        "Forum runtime inspection",
        f"ready: {payload.get('ready', False)}",
        f"default: {_line_for(payload.get('default') or {})}",
        "tiers:",
    ]
    for tier, spec in sorted((payload.get("tiers") or {}).items()):
        lines.append(f"- {tier}: {_line_for(spec)}")
    roster = payload.get("roster") or {}
    lines.append(
        "roster: "
        f"{roster.get('agents', 0)} agents; "
        f"{_tier_counts_text(roster.get('tiers') or {})}"
    )
    issues = payload.get("issues") or []
    if issues:
        lines.append("issues:")
        lines.extend(f"- {issue}" for issue in issues)
    return "\n".join(lines)


def _roster_tiers(roster: Roster) -> dict[str, int]:
    counts = Counter(agent.model_tier for agent in roster.agents)
    return {tier: counts.get(tier, 0) for tier in sorted(VALID_TIERS)}


def _executor_payload(spec: RuntimeExecutorSpec | None) -> dict:
    if spec is None:
        return _missing_payload()
    return spec.payload()


def _missing_payload() -> dict:
    return {"kind": "missing", "id": "", "source": "none", "detail": {}}


def _line_for(spec: dict) -> str:
    kind = spec.get("kind", "missing")
    identity = spec.get("id") or ""
    source = spec.get("source") or "none"
    if identity:
        return f"{kind} {identity} ({source})"
    return f"{kind} ({source})"


def _tier_counts_text(tiers: dict) -> str:
    return ", ".join(f"{tier}={count}" for tier, count in sorted(tiers.items()))
