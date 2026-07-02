import pytest

from forum.campaign import (
    Campaign,
    CampaignCycleError,
    Feature,
    Project,
    campaign_from_payload,
    campaign_payload,
    declare_campaign,
)
from forum.ledger import InMemoryStorage, Ledger


def make_ledger():
    ticks = iter(float(t) for t in range(1, 100000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _campaign():
    proj_forum = Project(
        project_id="crucible",
        owner="forum",
        priority=10,
        features=(
            Feature("c1", "schema", "backend", "build the schema", priority=5),
            Feature("c2", "endpoint", "backend", "wire the endpoint", priority=3, depends_on=("c1",)),
        ),
    )
    proj_ext = Project(
        project_id="telos",
        owner="external:telos",
        priority=8,
        features=(Feature("t1", "engine", "external", "ship the engine"),),
    )
    return Campaign("camp1", "flagship uplift", (proj_forum, proj_ext))


# --- A1: declare witnesses structure + payload round-trip + verify(deep) ---


def test_declare_appends_one_campaign_declared_entry_and_verifies():
    ledger = make_ledger()
    entry = declare_campaign(ledger, _campaign())
    assert entry.kind == "campaign_declared"
    declared = ledger.query(kind="campaign_declared")
    assert len(declared) == 1
    assert declared[0].seq == entry.seq
    body = ledger.get_payload(entry.payload_hash)
    assert body["campaign_id"] == "camp1"
    assert body["title"] == "flagship uplift"
    assert {p["project_id"] for p in body["projects"]} == {"crucible", "telos"}
    assert ledger.verify(deep=True) is True


def test_declare_respects_causal_parent():
    ledger = make_ledger()
    root = ledger.append(actor="client", kind="request", payload={"text": "go"})
    entry = declare_campaign(ledger, _campaign(), causal_parent=root.seq)
    assert entry.causal_parent == root.seq


def test_campaign_payload_round_trips():
    camp = _campaign()
    payload = campaign_payload(camp)
    restored = campaign_from_payload(payload)
    assert restored == camp
    # nested structure preserved
    proj = restored.feature_project("c2")
    assert proj.project_id == "crucible"
    feat = next(f for f in proj.features if f.feature_id == "c2")
    assert feat.depends_on == ("c1",)


def test_all_features_and_owner_helpers():
    camp = _campaign()
    ids = {f.feature_id for f in camp.all_features()}
    assert ids == {"c1", "c2", "t1"}
    assert camp.owner_of("c1") == "forum"
    assert camp.owner_of("t1") == "external:telos"
    assert camp.feature_project("t1").project_id == "telos"


# --- A2 (neg): dependency cycle -> CampaignCycleError, nothing appended ---


def test_dependency_cycle_raises_and_appends_nothing():
    proj = Project(
        project_id="p",
        owner="forum",
        priority=1,
        features=(
            Feature("a", "a", "x", "ia", depends_on=("b",)),
            Feature("b", "b", "x", "ib", depends_on=("a",)),
        ),
    )
    camp = Campaign("cyc", "cycle", (proj,))
    ledger = make_ledger()
    with pytest.raises(CampaignCycleError):
        declare_campaign(ledger, camp)
    assert ledger.count() == 0
    # validate() alone also raises without touching a ledger
    with pytest.raises(CampaignCycleError):
        camp.validate()


# --- A3 (neg): unknown dep + duplicate id ---


def test_duplicate_feature_id_raises_and_appends_nothing():
    proj = Project(
        project_id="p",
        owner="forum",
        priority=1,
        features=(
            Feature("dup", "a", "x", "ia"),
            Feature("dup", "b", "x", "ib"),
        ),
    )
    camp = Campaign("d", "dup", (proj,))
    ledger = make_ledger()
    with pytest.raises(ValueError):
        declare_campaign(ledger, camp)
    assert ledger.count() == 0


def test_unknown_dependency_raises_and_appends_nothing():
    proj = Project(
        project_id="p",
        owner="forum",
        priority=1,
        features=(Feature("a", "a", "x", "ia", depends_on=("ghost",)),),
    )
    camp = Campaign("u", "unknown", (proj,))
    ledger = make_ledger()
    with pytest.raises(ValueError):
        declare_campaign(ledger, camp)
    assert ledger.count() == 0


def test_cycle_error_is_a_value_error_subclass():
    # so callers can catch either the generic ValueError or the specific cycle error
    assert issubclass(CampaignCycleError, ValueError)
