from forum.campaign import Campaign, Feature, Project, declare_campaign
from forum.campaign_ingest import ingest_project_status
from forum.campaign_room import build_campaign_room, derive_campaign_next_actions
from forum.campaign_status import derive_campaign_status
from forum.ledger import InMemoryStorage, Ledger


def make_ledger():
    ticks = iter(float(t) for t in range(1, 100000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _campaign():
    proj = Project(
        project_id="crucible", owner="forum", priority=10,
        features=(
            Feature("c1", "schema", "backend", "build", priority=5),
            Feature("c2", "endpoint", "backend", "wire", priority=3, depends_on=("c1",)),
        ),
    )
    return Campaign("camp1", "uplift", (proj,))


def _witness_result(ledger, fid, ok):
    return ledger.append(
        actor="backend", kind="result",
        payload={"id": fid, "output": "out", "ok": ok, "model": "echo"},
    ).seq


# --- E1: campaign_room progress signal + next_actions ---


def test_campaign_room_has_progress_and_verification():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    room = build_campaign_room(ledger, "camp1")
    assert room["campaign_id"] == "camp1"
    assert room["verified"] is True
    assert "checkpoint" in room
    # progress signal: 0 of 2 done
    assert room["progress"]["done"] == 0
    assert room["progress"]["total"] == 2
    assert room["complete"] is False


def test_next_actions_dispatch_feature_for_highest_priority_runnable():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    status = derive_campaign_status(ledger, "camp1")
    actions = derive_campaign_next_actions(status)
    kinds = [a["kind"] for a in actions]
    assert "dispatch_feature" in kinds
    disp = next(a for a in actions if a["kind"] == "dispatch_feature")
    # c1 is the only runnable (c2 depends on it); highest-priority runnable dispatched
    assert disp["target"]["feature_id"] == "c1"
    assert disp["priority"] == "high"


def test_next_actions_unblock_for_blocked_feature():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    seq = _witness_result(ledger, "c1", ok=False)
    ledger.append(
        actor="campaign", kind="feature_status",
        payload={"campaign_id": "camp1", "project_id": "crucible",
                 "feature_id": "c1", "status": "failed", "reason": "boom", "witnessed_seq": seq},
    )
    status = derive_campaign_status(ledger, "camp1")
    actions = derive_campaign_next_actions(status)
    unblock = [a for a in actions if a["kind"] == "unblock"]
    assert unblock
    assert unblock[0]["target"]["feature_id"] == "c2"
    assert "c1" in unblock[0]["reason"]


def test_next_actions_investigate_for_violation():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    # fabricated done: witnessed_seq points at a failed result
    bad = _witness_result(ledger, "c1", ok=False)
    ledger.append(
        actor="rogue", kind="feature_status",
        payload={"campaign_id": "camp1", "project_id": "crucible",
                 "feature_id": "c1", "status": "done", "reason": "", "witnessed_seq": bad},
    )
    status = derive_campaign_status(ledger, "camp1")
    actions = derive_campaign_next_actions(status)
    investigate = [a for a in actions if a["kind"] == "investigate"]
    assert investigate
    assert investigate[0]["priority"] == "high"
    assert investigate[0]["target"]["feature_id"] == "c1"


def test_room_surfaces_ingested_project_status():
    ledger = make_ledger()
    proj = Project(
        project_id="crucible", owner="forum", priority=10,
        features=(Feature("c1", "schema", "backend", "build"),),
    )
    ext = Project(
        project_id="telos", owner="external:telos", priority=8,
        features=(Feature("t1", "engine", "external", "engine"),),
    )
    declare_campaign(ledger, Campaign("camp1", "uplift", (proj, ext)))
    ingest_project_status(
        ledger, "camp1", "telos", "in_progress",
        source="external:telos", reason="engine mid-build",
    )
    room = build_campaign_room(ledger, "camp1")
    telos = next(p for p in room["projects"] if p["project_id"] == "telos")
    assert telos["reported_status"] == "in_progress"
    assert telos["reported_source"] == "external:telos"
    assert room["verified"] is True


def test_next_actions_close_campaign_when_complete():
    ledger = make_ledger()
    proj = Project(
        project_id="p", owner="forum", priority=1,
        features=(Feature("a", "a", "x", "ia"),),
    )
    declare_campaign(ledger, Campaign("c", "t", (proj,)))
    seq = _witness_result(ledger, "a", ok=True)
    ledger.append(
        actor="campaign", kind="feature_status",
        payload={"campaign_id": "c", "project_id": "p",
                 "feature_id": "a", "status": "done", "reason": "", "witnessed_seq": seq},
    )
    status = derive_campaign_status(ledger, "c")
    actions = derive_campaign_next_actions(status)
    assert any(a["kind"] == "close_campaign" for a in actions)
