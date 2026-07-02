from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from forum.roster import Roster
from forum.routing import RouteResult

ROUTE_FRAME_SCHEMA = "forum.route-frame/v1"

_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class RouteFrame:
    schema: str
    agent: str | None
    domain: str
    intent: str
    posture: str
    delivery_profile: str
    model_tier: str | None
    executor: str | None
    proof_lane: str | None
    domain_lane: str | None
    human_contract: str
    signals: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _FrameRule:
    domain: str
    intent: str
    posture: str
    delivery_profile: str
    proof_lane: str | None
    domain_lane: str | None
    contract: str
    keywords: frozenset[str]
    agents: frozenset[str] = frozenset()


_GENERAL_CONTRACT = (
    "Answer as an operator: state the route, the uncertainty, and the next useful step."
)

_RULES: tuple[_FrameRule, ...] = (
    _FrameRule(
        domain="model-foundry",
        intent="validate",
        posture="architect",
        delivery_profile="engineer",
        proof_lane="validate",
        domain_lane="model-foundry",
        contract=(
            "Answer as a systems architect: name the mechanism, the gating evidence, "
            "and the next executable step."
        ),
        keywords=frozenset({
            "model",
            "models",
            "daemon",
            "eval",
            "evals",
            "promotion",
            "foundry",
            "gated",
            "gate",
            "self",
            "improving",
        }),
        agents=frozenset({"model-foundry"}),
    ),
    _FrameRule(
        domain="evidence",
        intent="investigate",
        posture="investigator",
        delivery_profile="researcher",
        proof_lane="observe",
        domain_lane="source-federation",
        contract=(
            "Answer as an investigator: separate observations from inference, cite the "
            "captured evidence, and preserve provenance."
        ),
        keywords=frozenset({
            "browser",
            "capture",
            "evidence",
            "source",
            "sources",
            "provenance",
            "screenshot",
            "screenshots",
            "dom",
            "crawl",
            "scrape",
            "page",
        }),
        agents=frozenset({"web-intel", "deep-research"}),
    ),
    _FrameRule(
        domain="validation",
        intent="validate",
        posture="reviewer",
        delivery_profile="engineer",
        proof_lane="verify",
        domain_lane="formal-proof",
        contract=(
            "Answer as a reviewer: identify the claim, the check performed, the result, "
            "and the remaining risk."
        ),
        keywords=frozenset({
            "review",
            "audit",
            "verify",
            "verification",
            "validate",
            "test",
            "tests",
            "quality",
            "regression",
            "proof",
        }),
        agents=frozenset({"code-review", "ci-cd"}),
    ),
    _FrameRule(
        domain="teaching",
        intent="synthesize",
        posture="teacher",
        delivery_profile="researcher",
        proof_lane="synthesize",
        domain_lane="learning-forge",
        contract=(
            "Answer as a teacher: build from the learner's current frame, give one clear "
            "example, and make the check for understanding explicit."
        ),
        keywords=frozenset({
            "teach",
            "explain",
            "learn",
            "learning",
            "lesson",
            "example",
            "course",
            "tutorial",
        }),
        agents=frozenset({"teaching"}),
    ),
    _FrameRule(
        domain="operator-platform",
        intent="coordinate",
        posture="operator",
        delivery_profile="executive",
        proof_lane="synthesize",
        domain_lane="frontier-foundry",
        contract=(
            "Answer as an operator: name the platform move, the tradeoff, the owner, "
            "and the next coordinated action."
        ),
        keywords=frozenset({
            "telos",
            "platform",
            "orchestration",
            "flagship",
            "operator",
            "workflow",
            "forum",
            "index",
            "harness",
            "agents",
        }),
        agents=frozenset({"project-telos", "function-routing"}),
    ),
    _FrameRule(
        domain="implementation",
        intent="execute",
        posture="architect",
        delivery_profile="engineer",
        proof_lane="execute",
        domain_lane=None,
        contract=(
            "Answer as an implementation architect: describe the change, the interface, "
            "the verification path, and the next executable step."
        ),
        keywords=frozenset({
            "build",
            "implement",
            "ship",
            "api",
            "database",
            "server",
            "endpoint",
            "code",
            "fix",
            "service",
        }),
        agents=frozenset({
            "backend",
            "frontend",
            "python-apps",
            "sdk-platform",
            "data-pipeline",
        }),
    ),
)


def derive_route_frame(
    text: str,
    route: RouteResult,
    roster: Roster | None = None,
) -> RouteFrame:
    """Derive the human-facing contract for a route from local signals only."""
    agent = route.decided if not route.needs_escalation else None
    model_tier, executor = _runtime_policy(agent, roster)
    tokens = frozenset(_TOKEN.findall(text.lower()))
    for rule in _RULES:
        signals = _signals(tokens, rule.keywords)
        if signals or (agent is not None and agent in rule.agents):
            return RouteFrame(
                schema=ROUTE_FRAME_SCHEMA,
                agent=agent,
                domain=rule.domain,
                intent=rule.intent,
                posture=rule.posture,
                delivery_profile=rule.delivery_profile,
                model_tier=model_tier,
                executor=executor,
                proof_lane=rule.proof_lane,
                domain_lane=rule.domain_lane,
                human_contract=rule.contract,
                signals=signals,
            )
    return RouteFrame(
        schema=ROUTE_FRAME_SCHEMA,
        agent=agent,
        domain="general",
        intent="coordinate",
        posture="operator",
        delivery_profile="operator",
        model_tier=model_tier,
        executor=executor,
        proof_lane=None,
        domain_lane=None,
        human_contract=_GENERAL_CONTRACT,
        signals=(),
    )


def frame_payload(frame: RouteFrame) -> dict:
    return {
        "schema": frame.schema,
        "agent": frame.agent,
        "domain": frame.domain,
        "intent": frame.intent,
        "posture": frame.posture,
        "delivery_profile": frame.delivery_profile,
        "model_tier": frame.model_tier,
        "executor": frame.executor,
        "proof_lane": frame.proof_lane,
        "domain_lane": frame.domain_lane,
        "human_contract": frame.human_contract,
        "signals": list(frame.signals),
    }


def _signals(tokens: frozenset[str], keywords: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(tokens.intersection(keywords)))


def _runtime_policy(agent: str | None, roster: Roster | None) -> tuple[str | None, str | None]:
    if agent is None or roster is None:
        return None, None
    spec = roster.by_name(agent)
    if spec is None:
        return None, None
    return spec.model_tier, spec.executor
