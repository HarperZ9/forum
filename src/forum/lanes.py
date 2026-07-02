from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from forum.ledger import Ledger


class LaneViolation(Enum):
    """Typed reasons the proof-lane gate refuses a route."""

    UNKNOWN_LANE = "unknown_lane"
    OVER_ROUTED = "over_routed"


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
class LaneRoute:
    """A route claim: this task wants this lane with these scopes."""

    task: str
    lane: str
    scopes: frozenset[str]


@dataclass(frozen=True, slots=True)
class LaneRejection:
    """The typed reason a route was refused.

    Carries the offending lane name, the exact scopes at fault, and the scopes
    the lane actually grants (empty for an unknown lane, which grants nothing),
    so a caller never needs a second vocabulary lookup to explain the refusal.
    """

    violation: LaneViolation
    lane: str
    excess: tuple[str, ...]
    granted: tuple[str, ...]


class LaneRouteError(Exception):
    """Raised after a rejected route has been witnessed in the ledger."""

    def __init__(self, rejection: LaneRejection) -> None:
        super().__init__(
            f"{rejection.violation.value}: lane {rejection.lane!r}, "
            f"excess scopes {list(rejection.excess)}, grants {list(rejection.granted)}"
        )
        self.rejection = rejection


def check_route(route: LaneRoute) -> LaneRejection | None:
    """Check one route against the closed vocabulary; None means well-formed.

    The decision keys off machine-checkable evidence only: membership of the
    lane name in the frozen vocabulary, and set arithmetic between the claimed
    scopes and the lane's granted scopes. Nothing a route's author writes can
    certify the route; only the vocabulary can. For an unknown lane every
    claimed scope is excess, because an unknown lane grants nothing.
    """
    spec = PROOF_LANES.get(route.lane)
    if spec is None:
        return LaneRejection(
            LaneViolation.UNKNOWN_LANE, route.lane, tuple(sorted(route.scopes)), ()
        )
    excess = route.scopes - spec.scopes
    if excess:
        return LaneRejection(
            LaneViolation.OVER_ROUTED,
            route.lane,
            tuple(sorted(excess)),
            tuple(sorted(spec.scopes)),
        )
    return None


def witness_route(
    ledger: Ledger, route: LaneRoute, *, causal_parent: int | None = None
) -> LaneRoute:
    """Gate a route through the proof-lane vocabulary, witnessed either way.

    A well-formed route is witnessed as a ``lane_route`` entry and returned
    unchanged. A route that names a lane outside the vocabulary, or claims a
    scope its lane does not grant (over-routing), is witnessed as a
    first-class ``lane_rejection`` entry, never a silent drop, and then
    refused with :class:`LaneRouteError`, which carries the typed rejection.
    """
    claimed = sorted(route.scopes)
    rejection = check_route(route)
    if rejection is None:
        ledger.append(
            actor="router",
            kind="lane_route",
            payload={"task": route.task, "lane": route.lane, "scopes": claimed},
            causal_parent=causal_parent,
        )
        return route
    ledger.append(
        actor="router",
        kind="lane_rejection",
        payload={
            "task": route.task,
            "lane": route.lane,
            "scopes": claimed,
            "violation": rejection.violation.value,
            "excess": list(rejection.excess),
            "granted": list(rejection.granted),
        },
        causal_parent=causal_parent,
    )
    raise LaneRouteError(rejection)
