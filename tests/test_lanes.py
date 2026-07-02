import pytest

from forum.lanes import (
    DOMAIN_LANES,
    PROOF_LANES,
    SCOPES,
    LaneRoute,
    LaneRouteError,
    LaneViolation,
    check_route,
    witness_route,
)
from forum.ledger import InMemoryStorage, Ledger


def _ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def test_vocabulary_is_closed_and_frozen():
    # the vocabulary is read-only at runtime; widening it is a code change
    with pytest.raises(TypeError):
        PROOF_LANES["root"] = None  # type: ignore[index]
    assert len(PROOF_LANES) == 5
    for name, spec in PROOF_LANES.items():
        assert spec.name == name
        assert isinstance(spec.scopes, frozenset)
        assert spec.scopes <= SCOPES
        assert "read" in spec.scopes  # every lane can at least read the record


def test_unknown_lane_is_rejected_and_witnessed():
    ledger = _ledger()
    req = ledger.append(actor="client", kind="request", payload={"text": "inspect the run"})
    route = LaneRoute(task="inspect the run", lane="root", scopes=frozenset({"read"}))
    with pytest.raises(LaneRouteError) as excinfo:
        witness_route(ledger, route, causal_parent=req.seq)
    assert excinfo.value.rejection.violation is LaneViolation.UNKNOWN_LANE
    assert excinfo.value.rejection.granted == ()  # an unknown lane grants nothing
    rejections = ledger.query(kind="lane_rejection")
    assert len(rejections) == 1
    body = ledger.get_payload(rejections[0].payload_hash)
    assert body["violation"] == "unknown_lane"
    assert body["lane"] == "root"
    assert body["granted"] == []  # an unknown lane grants nothing
    # a first-class witnessed event, chained to the request, in a verifiable record
    assert rejections[0].causal_parent == req.seq
    assert ledger.verify(deep=True) is True


def test_over_routed_route_is_rejected_and_witnessed():
    ledger = _ledger()
    # observe grants read only; claiming run on top of it is over-routing
    route = LaneRoute(
        task="read the record then mutate it",
        lane="observe",
        scopes=frozenset({"read", "run"}),
    )
    with pytest.raises(LaneRouteError) as excinfo:
        witness_route(ledger, route)
    rejection = excinfo.value.rejection
    assert rejection.violation is LaneViolation.OVER_ROUTED
    assert rejection.excess == ("run",)
    assert rejection.granted == ("read",)
    rejections = ledger.query(kind="lane_rejection")
    assert len(rejections) == 1
    body = ledger.get_payload(rejections[0].payload_hash)
    assert body["violation"] == "over_routed"
    assert body["excess"] == ["run"]
    assert body["granted"] == ["read"]
    assert ledger.verify(deep=True) is True


def test_route_cannot_self_certify_with_a_scope_string():
    # an approved-sounding scope outside the closed set is still over-routing;
    # the gate keys off the vocabulary, not what the route's author wrote
    route = LaneRoute(task="x", lane="validate", scopes=frozenset({"judge", "approved"}))
    rejection = check_route(route)
    assert rejection is not None
    assert rejection.violation is LaneViolation.OVER_ROUTED
    assert rejection.excess == ("approved",)
    assert "approved" not in SCOPES


def test_well_formed_route_passes_unchanged_and_is_witnessed():
    ledger = _ledger()
    route = LaneRoute(task="run the build", lane="execute", scopes=frozenset({"read", "run"}))
    out = witness_route(ledger, route)
    assert out is route  # pass means pass: the same route object, unchanged
    accepted = ledger.query(kind="lane_route")
    assert len(accepted) == 1
    body = ledger.get_payload(accepted[0].payload_hash)
    assert body == {
        "task": "run the build",
        "lane": "execute",
        "domain": None,
        "scopes": ["read", "run"],
        "confidence": None,
    }
    assert ledger.query(kind="lane_rejection") == []
    assert ledger.verify(deep=True) is True


def test_domain_vocabulary_is_closed_and_frozen():
    # the domain axis is a second closed vocabulary; widening it is a code change
    with pytest.raises(TypeError):
        DOMAIN_LANES["shadow-lane"] = None  # type: ignore[index]
    assert len(DOMAIN_LANES) == 10
    assert "source-federation" in DOMAIN_LANES  # the 0143 gap, now named
    for name, spec in DOMAIN_LANES.items():
        assert spec.name == name
        assert spec.charter  # every domain lane declares what it is for


def test_unknown_domain_lane_is_rejected_and_witnessed():
    ledger = _ledger()
    req = ledger.append(
        actor="client", kind="request", payload={"text": "federate the archives"}
    )
    route = LaneRoute(
        task="federate the archives",
        lane="observe",
        scopes=frozenset({"read"}),
        domain="archive-federation",  # not in the closed domain set
        confidence=0.12,
    )
    with pytest.raises(LaneRouteError) as excinfo:
        witness_route(ledger, route, causal_parent=req.seq)
    rejection = excinfo.value.rejection
    assert rejection.violation is LaneViolation.UNKNOWN_DOMAIN
    assert rejection.domain == "archive-federation"
    rejections = ledger.query(kind="lane_rejection")
    assert len(rejections) == 1
    body = ledger.get_payload(rejections[0].payload_hash)
    # the supervision contract: both axes, confidence, and a typed reason code
    assert set(body) == {
        "task", "lane", "domain", "scopes", "confidence", "violation", "excess", "granted",
    }
    assert body["violation"] == "unknown_domain"
    assert body["lane"] == "observe"
    assert body["domain"] == "archive-federation"
    assert body["confidence"] == 0.12
    assert rejections[0].causal_parent == req.seq
    assert ledger.verify(deep=True) is True


def test_well_formed_two_axis_route_passes_and_is_witnessed():
    ledger = _ledger()
    route = LaneRoute(
        task="run the simulation suite",
        lane="execute",
        scopes=frozenset({"read", "run"}),
        domain="scientific-runtime",
        confidence=0.91,
    )
    out = witness_route(ledger, route)
    assert out is route
    accepted = ledger.query(kind="lane_route")
    assert len(accepted) == 1
    body = ledger.get_payload(accepted[0].payload_hash)
    assert body == {
        "task": "run the simulation suite",
        "lane": "execute",
        "domain": "scientific-runtime",
        "scopes": ["read", "run"],
        "confidence": 0.91,
    }
    assert ledger.query(kind="lane_rejection") == []
    assert ledger.verify(deep=True) is True


def test_domain_axis_is_orthogonal_to_scopes():
    # a valid domain never launders an over-routed scope claim
    route = LaneRoute(
        task="mutate under a formal-proof banner",
        lane="observe",
        scopes=frozenset({"read", "run"}),
        domain="formal-proof",
    )
    rejection = check_route(route)
    assert rejection is not None
    assert rejection.violation is LaneViolation.OVER_ROUTED
    assert rejection.excess == ("run",)
    # and no domain lane grants any scope: the axes stay orthogonal
    for spec in DOMAIN_LANES.values():
        assert not hasattr(spec, "scopes")
