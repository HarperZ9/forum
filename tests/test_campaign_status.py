from forum.campaign import Campaign, Feature, Project, declare_campaign
from forum.campaign_status import derive_campaign_status, derive_next_features
from forum.ledger import InMemoryStorage, Ledger
from forum.storage import FileStorage


def make_ledger():
    ticks = iter(float(t) for t in range(1, 100000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _campaign():
    forum_proj = Project(
        project_id="crucible",
        owner="forum",
        priority=10,
        features=(
            Feature("c1", "schema", "backend", "build schema", priority=5),
            Feature("c2", "endpoint", "backend", "endpoint", priority=3, depends_on=("c1",)),
        ),
    )
    ext_proj = Project(
        project_id="telos",
        owner="external:telos",
        priority=8,
        features=(Feature("t1", "engine", "external", "engine"),),
    )
    return Campaign("camp1", "uplift", (forum_proj, ext_proj))


def _witness_result(ledger, feature_id, ok):
    """Append a real result entry (as dispatch would) and return its seq."""
    return ledger.append(
        actor="backend",
        kind="result",
        payload={"id": feature_id, "output": "out", "ok": ok, "model": "echo"},
    ).seq


# --- B1: status reduces from ledger; re-derivable over a fresh Ledger ---


def test_status_reduces_declared_structure():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    status = derive_campaign_status(ledger, "camp1")
    assert status["campaign_id"] == "camp1"
    assert status["title"] == "uplift"
    assert status["complete"] is False
    ids = {f["feature_id"] for f in status["features"]}
    assert ids == {"c1", "c2", "t1"}
    # all pending initially
    assert status["counts"]["pending"] == 3
    assert status["counts"]["done"] == 0
    c1 = next(f for f in status["features"] if f["feature_id"] == "c1")
    assert c1["owner"] == "forum"
    assert c1["status"] == "pending"


def test_status_folds_feature_status_done_with_witness():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    seq = _witness_result(ledger, "c1", ok=True)
    ledger.append(
        actor="campaign",
        kind="feature_status",
        payload={
            "campaign_id": "camp1", "project_id": "crucible", "feature_id": "c1",
            "status": "done", "reason": "", "witnessed_seq": seq,
        },
    )
    status = derive_campaign_status(ledger, "camp1")
    c1 = next(f for f in status["features"] if f["feature_id"] == "c1")
    assert c1["status"] == "done"
    assert c1["witnessed_seq"] == seq
    assert c1.get("violation") is None
    assert status["counts"]["done"] == 1


def test_status_is_re_derivable_over_fresh_ledger_same_storage(tmp_path):
    d = str(tmp_path / "led")
    led = Ledger(FileStorage(d))
    declare_campaign(led, _campaign())
    seq = led.append(
        actor="backend", kind="result",
        payload={"id": "c1", "output": "o", "ok": True, "model": "echo"},
    ).seq
    led.append(
        actor="campaign", kind="feature_status",
        payload={"campaign_id": "camp1", "project_id": "crucible",
                 "feature_id": "c1", "status": "done", "reason": "", "witnessed_seq": seq},
    )
    led.sync()
    first = derive_campaign_status(led, "camp1")
    # a fresh Ledger over the same storage rebuilds the identical status
    led2 = Ledger(FileStorage(d))
    second = derive_campaign_status(led2, "camp1")
    assert first == second
    assert led2.verify(deep=True) is True


# --- B2 (MARQUEE neg): fabricated done -> unwitnessed + violation ---


def test_fabricated_done_witness_points_to_failed_result_is_unwitnessed():
    """A feature_status{done} whose witnessed_seq points at a result with ok=False
    is a fabricated done: reported unwitnessed + violation, counted unwitnessed
    NOT done, campaign not complete."""
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    bad_seq = _witness_result(ledger, "c1", ok=False)  # a FAILED result
    ledger.append(
        actor="rogue", kind="feature_status",
        payload={"campaign_id": "camp1", "project_id": "crucible",
                 "feature_id": "c1", "status": "done", "reason": "", "witnessed_seq": bad_seq},
    )
    status = derive_campaign_status(ledger, "camp1")
    c1 = next(f for f in status["features"] if f["feature_id"] == "c1")
    assert c1["status"] == "unwitnessed"
    assert c1["violation"] == "claimed done without witnessing result"
    assert status["counts"]["unwitnessed"] == 1
    assert status["counts"]["done"] == 0
    assert status["complete"] is False


def test_fabricated_done_witness_points_to_non_result_entry():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    # point at the campaign_declared entry (seq 0), not a result
    ledger.append(
        actor="rogue", kind="feature_status",
        payload={"campaign_id": "camp1", "project_id": "crucible",
                 "feature_id": "c1", "status": "done", "reason": "", "witnessed_seq": 0},
    )
    status = derive_campaign_status(ledger, "camp1")
    c1 = next(f for f in status["features"] if f["feature_id"] == "c1")
    assert c1["status"] == "unwitnessed"
    assert c1["violation"] == "claimed done without witnessing result"
    assert status["counts"]["done"] == 0


def test_fabricated_done_missing_witnessed_seq():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    ledger.append(
        actor="rogue", kind="feature_status",
        payload={"campaign_id": "camp1", "project_id": "crucible",
                 "feature_id": "c1", "status": "done", "reason": ""},  # no witnessed_seq
    )
    status = derive_campaign_status(ledger, "camp1")
    c1 = next(f for f in status["features"] if f["feature_id"] == "c1")
    assert c1["status"] == "unwitnessed"
    assert c1["violation"] == "claimed done without witnessing result"


def test_witnessed_seq_pointing_to_other_feature_result_is_rejected():
    """The witness must be a result for THIS feature id, not any ok=True result."""
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    other_seq = _witness_result(ledger, "c2", ok=True)  # result for c2, not c1
    ledger.append(
        actor="rogue", kind="feature_status",
        payload={"campaign_id": "camp1", "project_id": "crucible",
                 "feature_id": "c1", "status": "done", "reason": "", "witnessed_seq": other_seq},
    )
    status = derive_campaign_status(ledger, "camp1")
    c1 = next(f for f in status["features"] if f["feature_id"] == "c1")
    assert c1["status"] == "unwitnessed"
    assert c1["violation"] == "claimed done without witnessing result"


# --- B3: next_features respects deps + priority ---


def test_next_features_runnable_when_deps_done_sorted_by_priority():
    ledger = make_ledger()
    # two independent forum features, different priorities
    proj = Project(
        project_id="p", owner="forum", priority=1,
        features=(
            Feature("low", "l", "x", "il", priority=1),
            Feature("high", "h", "x", "ih", priority=9),
        ),
    )
    declare_campaign(ledger, Campaign("c", "t", (proj,)))
    status = derive_campaign_status(ledger, "c")
    nxt = derive_next_features(status)
    runnable_ids = [f["feature_id"] for f in nxt["runnable"]]
    assert runnable_ids == ["high", "low"]  # priority desc


def test_next_features_dep_not_done_is_not_runnable():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    status = derive_campaign_status(ledger, "camp1")
    nxt = derive_next_features(status)
    runnable_ids = {f["feature_id"] for f in nxt["runnable"]}
    assert "c1" in runnable_ids  # no deps
    assert "c2" not in runnable_ids  # depends on c1 (pending)


def test_next_features_c2_runnable_after_c1_done():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    seq = _witness_result(ledger, "c1", ok=True)
    ledger.append(
        actor="campaign", kind="feature_status",
        payload={"campaign_id": "camp1", "project_id": "crucible",
                 "feature_id": "c1", "status": "done", "reason": "", "witnessed_seq": seq},
    )
    status = derive_campaign_status(ledger, "camp1")
    nxt = derive_next_features(status)
    runnable_ids = {f["feature_id"] for f in nxt["runnable"]}
    assert "c2" in runnable_ids
    assert "c1" not in runnable_ids  # already done


# --- B4 (neg): blocked dep surfaces reason + not runnable ---


def test_blocked_dep_surfaces_reason_and_not_runnable():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    # c1 failed -> c2 (depends on c1) is blocked
    seq = _witness_result(ledger, "c1", ok=False)
    ledger.append(
        actor="campaign", kind="feature_status",
        payload={"campaign_id": "camp1", "project_id": "crucible",
                 "feature_id": "c1", "status": "failed", "reason": "boom", "witnessed_seq": seq},
    )
    status = derive_campaign_status(ledger, "camp1")
    nxt = derive_next_features(status)
    runnable_ids = {f["feature_id"] for f in nxt["runnable"]}
    assert "c2" not in runnable_ids
    blocked_ids = {f["feature_id"] for f in nxt["blocked"]}
    assert "c2" in blocked_ids
    c2_blocked = next(f for f in nxt["blocked"] if f["feature_id"] == "c2")
    assert "c1" in c2_blocked["reason"]
    # c2's blocking_deps surfaced on the status feature too
    c2 = next(f for f in status["features"] if f["feature_id"] == "c2")
    assert "c1" in c2["blocking_deps"]
    assert c2["deps_met"] is False


# --- B5: external-owned never runnable ---


def test_external_owned_feature_never_runnable():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    status = derive_campaign_status(ledger, "camp1")
    nxt = derive_next_features(status)
    runnable_ids = {f["feature_id"] for f in nxt["runnable"]}
    assert "t1" not in runnable_ids  # external:telos owned
    t1 = next(f for f in status["features"] if f["feature_id"] == "t1")
    assert t1["owner"] == "external:telos"


def test_latest_feature_status_wins():
    ledger = make_ledger()
    declare_campaign(ledger, _campaign())
    ledger.append(
        actor="campaign", kind="feature_status",
        payload={"campaign_id": "camp1", "project_id": "crucible",
                 "feature_id": "c1", "status": "in_progress", "reason": ""},
    )
    seq = _witness_result(ledger, "c1", ok=True)
    ledger.append(
        actor="campaign", kind="feature_status",
        payload={"campaign_id": "camp1", "project_id": "crucible",
                 "feature_id": "c1", "status": "done", "reason": "", "witnessed_seq": seq},
    )
    status = derive_campaign_status(ledger, "camp1")
    c1 = next(f for f in status["features"] if f["feature_id"] == "c1")
    assert c1["status"] == "done"  # latest-wins


def test_complete_when_all_forum_features_done():
    ledger = make_ledger()
    # a forum-only campaign so completeness is reachable
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
    assert status["complete"] is True
