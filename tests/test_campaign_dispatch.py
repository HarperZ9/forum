import asyncio

from forum.campaign import Campaign, Feature, Project, declare_campaign
from forum.campaign_dispatch import run_campaign, run_campaign_round
from forum.campaign_status import derive_campaign_status, derive_next_features
from forum.executor import EchoExecutor, Result
from forum.gates import GatePolicy, resolve_gate
from forum.ledger import InMemoryStorage, Ledger


def make_ledger():
    ticks = iter(float(t) for t in range(1, 1000000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _forum_campaign():
    proj = Project(
        project_id="crucible", owner="forum", priority=10,
        features=(
            Feature("c1", "schema", "backend", "build schema", priority=5),
            Feature("c2", "endpoint", "backend", "endpoint", priority=3, depends_on=("c1",)),
        ),
    )
    return Campaign("camp1", "uplift", (proj,))


class RaisingExecutor:
    """Fails one named feature (raises); every other feature echoes success."""

    def __init__(self, fail_id):
        self.fail_id = fail_id

    async def run(self, assignment):
        if assignment.task_id == self.fail_id:
            raise RuntimeError("boom")
        return Result(assignment.task_id, assignment.agent, f"done: {assignment.instruction}")


# --- C1: round dispatches runnable, witnesses done with real witnessed_seq ---


def test_round_dispatches_runnable_and_witnesses_done():
    ledger = make_ledger()
    campaign = _forum_campaign()
    declare_campaign(ledger, campaign)
    asyncio.run(run_campaign_round(ledger, campaign, EchoExecutor()))

    # a campaign_dispatch wave was witnessed
    disp = ledger.query(kind="campaign_dispatch")
    assert len(disp) == 1
    wave = ledger.get_payload(disp[0].payload_hash)["wave"]
    assert wave == ["c1"]  # only c1 runnable in round 1 (c2 depends on c1)

    status = derive_campaign_status(ledger, "camp1")
    c1 = next(f for f in status["features"] if f["feature_id"] == "c1")
    assert c1["status"] == "done"
    # the witnessed_seq points at a real ok=True result for c1
    result_entry = ledger.get(c1["witnessed_seq"])
    assert result_entry.kind == "result"
    body = ledger.get_payload(result_entry.payload_hash)
    assert body["id"] == "c1" and body["ok"] is True
    assert c1.get("violation") is None

    # campaign_result snapshot appended, chain verifies
    assert ledger.query(kind="campaign_result")
    assert ledger.verify(deep=True) is True


# --- C2: best-effort, a failing feature does not halt the round/campaign ---


def test_failing_feature_does_not_halt_and_dependents_blocked():
    ledger = make_ledger()
    # two independent forum features + one depending on the failing one
    proj = Project(
        project_id="p", owner="forum", priority=1,
        features=(
            Feature("bad", "b", "x", "will fail", priority=9),
            Feature("good", "g", "x", "will pass", priority=8),
            Feature("dependent", "d", "x", "needs bad", priority=7, depends_on=("bad",)),
        ),
    )
    campaign = Campaign("c", "t", (proj,))
    declare_campaign(ledger, campaign)

    asyncio.run(run_campaign(ledger, campaign, RaisingExecutor("bad")))

    status = derive_campaign_status(ledger, "c")
    by_id = {f["feature_id"]: f for f in status["features"]}
    assert by_id["bad"]["status"] == "failed"
    assert "boom" in by_id["bad"]["reason"]
    assert by_id["good"]["status"] == "done"  # sibling still ran and succeeded
    # dependent is surfaced as blocked, not silently dropped
    assert by_id["dependent"]["status"] == "blocked"
    # campaign is NOT complete (a forum feature failed), but the loop terminated
    assert status["complete"] is False
    # no runnable left -> fixed point reached despite the failure
    assert derive_next_features(status)["runnable"] == []
    assert ledger.verify(deep=True) is True


# --- C3: run_campaign reaches fixed point across a dep chain ---


def test_run_campaign_reaches_fixed_point_dep_chain():
    ledger = make_ledger()
    proj = Project(
        project_id="p", owner="forum", priority=1,
        features=(
            Feature("a", "a", "x", "ia"),
            Feature("b", "b", "x", "ib", depends_on=("a",)),
            Feature("d", "d", "x", "id", depends_on=("b",)),
        ),
    )
    campaign = Campaign("chain", "t", (proj,))
    declare_campaign(ledger, campaign)

    asyncio.run(run_campaign(ledger, campaign, EchoExecutor()))

    status = derive_campaign_status(ledger, "chain")
    assert status["complete"] is True
    assert status["counts"]["done"] == 3
    # each done points at a real witnessed result
    for f in status["features"]:
        assert f["status"] == "done"
        rbody = ledger.get_payload(ledger.get(f["witnessed_seq"]).payload_hash)
        assert rbody["id"] == f["feature_id"] and rbody["ok"] is True
    assert ledger.verify(deep=True) is True


# --- C4: concurrency budget respected ---


def test_budget_caps_features_dispatched_per_round():
    ledger = make_ledger()
    proj = Project(
        project_id="p", owner="forum", priority=1,
        features=tuple(
            Feature(f"f{i}", f"f{i}", "x", f"i{i}", priority=i) for i in range(5)
        ),
    )
    campaign = Campaign("b", "t", (proj,))
    declare_campaign(ledger, campaign)

    # budget=2: only 2 of the 5 runnable features dispatched this round
    asyncio.run(run_campaign_round(ledger, campaign, EchoExecutor(), budget=2))
    wave = ledger.get_payload(ledger.query(kind="campaign_dispatch")[0].payload_hash)["wave"]
    assert len(wave) == 2
    # highest priority first: f4, f3
    assert wave == ["f4", "f3"]


def test_run_campaign_completes_all_despite_budget():
    ledger = make_ledger()
    proj = Project(
        project_id="p", owner="forum", priority=1,
        features=tuple(
            Feature(f"f{i}", f"f{i}", "x", f"i{i}", priority=i) for i in range(5)
        ),
    )
    campaign = Campaign("b", "t", (proj,))
    declare_campaign(ledger, campaign)
    asyncio.run(run_campaign(ledger, campaign, EchoExecutor(), budget=2))
    status = derive_campaign_status(ledger, "b")
    assert status["complete"] is True
    assert status["counts"]["done"] == 5


# --- C5 (gate integration): a gated feature pauses, no done until approved ---


def test_gated_feature_pauses_until_resolved():
    ledger = make_ledger()
    proj = Project(
        project_id="p", owner="forum", priority=1,
        features=(Feature("g1", "g", "x", "gated work"),),
    )
    campaign = Campaign("gate", "t", (proj,))
    declare_campaign(ledger, campaign)

    # gate wave 0 of the round's plan
    gates = GatePolicy(frozenset({0}), "approve g1?")
    asyncio.run(run_campaign_round(ledger, campaign, EchoExecutor(), gates=gates))

    # paused: a gate_pending exists, no feature_status done, g1 still pending
    assert ledger.query(kind="gate_pending")
    status = derive_campaign_status(ledger, "gate")
    g1 = next(f for f in status["features"] if f["feature_id"] == "g1")
    assert g1["status"] == "pending"
    # no result witnessed for g1 yet
    result_ids = {ledger.get_payload(e.payload_hash).get("id") for e in ledger.query(kind="result")}
    assert "g1" not in result_ids

    # resolve the gate, then re-run the round with resume=True
    plan_seq = ledger.query(kind="plan")[0].seq
    resolve_gate(ledger, plan_seq, 0, "gate_approved", approver="op")
    asyncio.run(run_campaign_round(ledger, campaign, EchoExecutor(), gates=gates, resume=True))

    status = derive_campaign_status(ledger, "gate")
    g1 = next(f for f in status["features"] if f["feature_id"] == "g1")
    assert g1["status"] == "done"
    assert ledger.verify(deep=True) is True
