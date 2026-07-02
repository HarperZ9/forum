from forum.campaign import Campaign, Feature, Project, declare_campaign
from forum.campaign_ingest import ingest_feature_status, ingest_project_status
from forum.campaign_status import derive_campaign_status
from forum.ledger import InMemoryStorage, Ledger


def make_ledger():
    ticks = iter(float(t) for t in range(1, 100000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _campaign():
    forum_proj = Project(
        project_id="crucible", owner="forum", priority=10,
        features=(Feature("c1", "schema", "backend", "build"),),
    )
    ext_proj = Project(
        project_id="telos", owner="external:telos", priority=8,
        features=(Feature("t1", "engine", "external", "engine"),),
    )
    return Campaign("camp1", "uplift", (forum_proj, ext_proj))


# --- D1: external project status appears with source, no forum task/result ---


def test_ingest_project_status_records_without_executing():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    entry = ingest_project_status(
        ledger, "camp1", "telos", "in_progress",
        source="external:telos", reason="engine mid-build",
    )
    assert entry.kind == "project_status"
    body = ledger.get_payload(entry.payload_hash)
    assert body["project_id"] == "telos"
    assert body["status"] == "in_progress"
    assert body["source"] == "external:telos"
    # no forum task or result was created for the external project
    assert ledger.query(kind="task") == []
    assert ledger.query(kind="result") == []
    assert ledger.verify(deep=True) is True


# --- D2: external feature done labeled not-forum-witnessed, no violation ---


def test_ingest_external_feature_done_labeled_not_forum_witnessed():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    ingest_feature_status(
        ledger, "camp1", "telos", "t1", "done",
        source="external:telos", reason="shipped",
    )
    status = derive_campaign_status(ledger, "camp1")
    t1 = next(f for f in status["features"] if f["feature_id"] == "t1")
    assert t1["status"] == "done"
    # labeled as external, NOT a forum-witnessed done, and never a violation
    assert t1["external"] is True
    assert t1["external_source"] == "external:telos"
    assert t1.get("violation") is None
    # no forum result entry backs it
    assert ledger.query(kind="result") == []
    assert ledger.verify(deep=True) is True


def test_external_done_counts_as_done_but_is_distinct_from_forum_done():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    ingest_feature_status(ledger, "camp1", "telos", "t1", "done", source="external:telos")
    status = derive_campaign_status(ledger, "camp1")
    t1 = next(f for f in status["features"] if f["feature_id"] == "t1")
    # external done has no forum witnessed_seq (never conflated with a forum result)
    assert t1["witnessed_seq"] is None
    assert t1["external_source"] == "external:telos"


# --- D3: an ingested project_status actually SURFACES in derived status ---


def test_ingest_project_status_surfaces_in_derived_status():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    ingest_project_status(
        ledger, "camp1", "telos", "in_progress",
        source="external:telos", reason="engine mid-build",
    )
    status = derive_campaign_status(ledger, "camp1")
    telos = next(p for p in status["projects"] if p["project_id"] == "telos")
    # the reported project status is not write-only dead data: it is read back
    assert telos["reported_status"] == "in_progress"
    assert telos["reported_source"] == "external:telos"
    assert telos["reported_reason"] == "engine mid-build"
    # a project with no ingested status carries no reported status
    crucible = next(p for p in status["projects"] if p["project_id"] == "crucible")
    assert crucible["reported_status"] is None
    assert crucible["reported_source"] is None


def test_project_status_latest_wins():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    ingest_project_status(ledger, "camp1", "telos", "in_progress", source="external:telos")
    ingest_project_status(ledger, "camp1", "telos", "done", source="external:telos", reason="shipped")
    status = derive_campaign_status(ledger, "camp1")
    telos = next(p for p in status["projects"] if p["project_id"] == "telos")
    assert telos["reported_status"] == "done"
    assert telos["reported_reason"] == "shipped"
