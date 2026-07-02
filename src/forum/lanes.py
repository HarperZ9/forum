from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from forum.ledger import Ledger


class LaneViolation(Enum):
    """Typed reasons the proof-lane gate refuses a route."""

    UNKNOWN_LANE = "unknown_lane"
    OVER_ROUTED = "over_routed"
    UNKNOWN_DOMAIN = "unknown_domain"


@dataclass(frozen=True, slots=True)
class LaneSpec:
    """One proof lane: a name, its authority, and the scopes it grants."""

    name: str
    authority: str
    scopes: frozenset[str]


def _lane(name: str, authority: str, *scopes: str) -> tuple[str, LaneSpec]:
    return name, LaneSpec(name, authority, frozenset(scopes))


# The closed proof-lane vocabulary. A route may only claim a lane named here,
# and only the scopes that lane grants. The mapping is read-only on purpose:
# widening the vocabulary is a code change with tests, never a runtime edit.
PROOF_LANES: MappingProxyType[str, LaneSpec] = MappingProxyType(
    dict(
        (
            _lane("observe", "reads witnessed evidence; changes nothing", "read"),
            _lane("execute", "runs a task and produces a witnessed result", "read", "run"),
            _lane("validate", "judges an existing witnessed result", "read", "judge"),
            _lane("synthesize", "combines witnessed results into one answer", "read", "combine"),
            _lane("verify", "attests an answer against an external check", "read", "attest"),
        )
    )
)

# Every scope any lane grants; a scope outside this set is grantable by no lane.
SCOPES: frozenset[str] = frozenset().union(*(s.scopes for s in PROOF_LANES.values()))


@dataclass(frozen=True, slots=True)
class DomainSpec:
    """One domain lane: a name and the charter that says what it is for.

    A domain lane grants no scopes. Scopes belong to the verb axis
    (:data:`PROOF_LANES`); the domain axis only names which body of work a
    route belongs to, so a valid domain can never launder a scope claim.
    """

    name: str
    charter: str


def _domain(name: str, charter: str) -> tuple[str, DomainSpec]:
    return name, DomainSpec(name, charter)


# The closed domain-lane vocabulary, the second axis of a route. A route may
# carry (verb lane, domain lane); the domain names which body of work the
# route belongs to. Same rule as the verb axis: read-only on purpose, widening
# it is a code change with tests, never a runtime edit. When routing keeps
# escalating on work no domain here covers, the answer is a witnessed
# vocabulary-gap receipt (forum.lane_gaps), not a quiet new lane.
DOMAIN_LANES: MappingProxyType[str, DomainSpec] = MappingProxyType(
    dict(
        (
            _domain("frontier-foundry", "frontier capability work under gated evaluation"),
            _domain("research-foundry", "research intake and synthesis over recorded sources"),
            _domain("model-foundry", "model training, evaluation, and gated promotion"),
            _domain("scientific-runtime", "scientific computation with re-checkable results"),
            _domain("formal-proof", "machine-checkable proofs and verifier verdicts"),
            _domain("bio-evidence", "biological evidence handling under provenance controls"),
            _domain("robotics-control", "physical actuation under bounded authority"),
            _domain("visual-truth", "visual and rendered output checked against ground truth"),
            _domain("learning-forge", "learning material built and graded from recorded runs"),
            _domain("source-federation", "external sources federated with per-source receipts"),
        )
    )
)


@dataclass(frozen=True, slots=True)
class LaneRoute:
    """A route claim: this task wants this verb lane with these scopes.

    The two optional fields are the second axis and the routing signal:
    ``domain`` names the domain lane the work belongs to (validated against
    :data:`DOMAIN_LANES` when present), and ``confidence`` carries the
    router's score when one exists, so accepted and rejected routes alike
    land in the ledger with enough typed fields to reuse as supervision data.
    """

    task: str
    lane: str
    scopes: frozenset[str]
    domain: str | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class LaneRejection:
    """The typed reason a route was refused.

    Carries the offending lane name, the exact scopes at fault, and the scopes
    the lane actually grants (empty for an unknown lane, which grants nothing),
    so a caller never needs a second vocabulary lookup to explain the refusal.
    ``domain`` carries the route's domain claim, which for an unknown-domain
    refusal is the offending name itself.
    """

    violation: LaneViolation
    lane: str
    excess: tuple[str, ...]
    granted: tuple[str, ...]
    domain: str | None = None


class LaneRouteError(Exception):
    """Raised after a rejected route has been witnessed in the ledger."""

    def __init__(self, rejection: LaneRejection) -> None:
        super().__init__(
            f"{rejection.violation.value}: lane {rejection.lane!r}, "
            f"domain {rejection.domain!r}, "
            f"excess scopes {list(rejection.excess)}, grants {list(rejection.granted)}"
        )
        self.rejection = rejection


def check_route(route: LaneRoute) -> LaneRejection | None:
    """Check one route against both closed vocabularies; None means well-formed.

    The decision keys off machine-checkable evidence only: membership of the
    verb-lane name in the frozen vocabulary, membership of the domain name (if
    the route carries one) in the frozen domain vocabulary, and set arithmetic
    between the claimed scopes and the lane's granted scopes. Nothing a
    route's author writes can certify the route; only the vocabularies can.
    For an unknown lane every claimed scope is excess, because an unknown lane
    grants nothing.
    """
    spec = PROOF_LANES.get(route.lane)
    if spec is None:
        return LaneRejection(
            LaneViolation.UNKNOWN_LANE,
            route.lane,
            tuple(sorted(route.scopes)),
            (),
            route.domain,
        )
    excess = route.scopes - spec.scopes
    if excess:
        return LaneRejection(
            LaneViolation.OVER_ROUTED,
            route.lane,
            tuple(sorted(excess)),
            tuple(sorted(spec.scopes)),
            route.domain,
        )
    if route.domain is not None and route.domain not in DOMAIN_LANES:
        return LaneRejection(
            LaneViolation.UNKNOWN_DOMAIN,
            route.lane,
            (),
            tuple(sorted(spec.scopes)),
            route.domain,
        )
    return None


def witness_route(
    ledger: Ledger, route: LaneRoute, *, causal_parent: int | None = None
) -> LaneRoute:
    """Gate a route through both lane vocabularies, witnessed either way.

    A well-formed route is witnessed as a ``lane_route`` entry and returned
    unchanged. A route that names a verb lane outside the vocabulary, claims a
    scope its lane does not grant (over-routing), or names a domain lane
    outside the closed domain set, is witnessed as a first-class
    ``lane_rejection`` entry, never a silent drop, and then refused with
    :class:`LaneRouteError`, which carries the typed rejection.

    Both payloads carry the same typed fields (task, both lane axes, scopes,
    confidence, and on rejection the reason code with excess and granted
    scopes), so accepted and rejected routes alike can be read back from the
    ledger as labeled routing examples.
    """
    claimed = sorted(route.scopes)
    rejection = check_route(route)
    if rejection is None:
        ledger.append(
            actor="router",
            kind="lane_route",
            payload={
                "task": route.task,
                "lane": route.lane,
                "domain": route.domain,
                "scopes": claimed,
                "confidence": route.confidence,
            },
            causal_parent=causal_parent,
        )
        return route
    ledger.append(
        actor="router",
        kind="lane_rejection",
        payload={
            "task": route.task,
            "lane": route.lane,
            "domain": route.domain,
            "scopes": claimed,
            "confidence": route.confidence,
            "violation": rejection.violation.value,
            "excess": list(rejection.excess),
            "granted": list(rejection.granted),
        },
        causal_parent=causal_parent,
    )
    raise LaneRouteError(rejection)
