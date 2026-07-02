from __future__ import annotations

from forum.campaign import Campaign
from forum.campaign_status import derive_campaign_status, derive_next_features
from forum.dispatch import dispatch_plan
from forum.executor import Executor
from forum.gates import GatePolicy
from forum.ledger import Ledger
from forum.plan import Plan, Task


def _campaign_result_snapshot(ledger: Ledger, campaign_id: str) -> None:
    """Witness a campaign_result snapshot. The reducer never trusts it; it always
    recomputes from feature_status. The snapshot is a convenience marker only."""
    status = derive_campaign_status(ledger, campaign_id)
    counts = status["counts"]
    ledger.append(
        actor="campaign",
        kind="campaign_result",
        payload={
            "campaign_id": campaign_id,
            "done": counts["done"],
            "in_progress": counts["in_progress"],
            "blocked": counts["blocked"],
            "failed": counts["failed"],
            "complete": status["complete"],
        },
    )


def _witness_blocked(ledger: Ledger, campaign: Campaign, campaign_id: str) -> None:
    """Append feature_status{blocked} for any pending feature whose dep is
    failed/blocked/unwitnessed, so a stalled dependent is surfaced, not dropped."""
    status = derive_campaign_status(ledger, campaign_id)
    blocked = derive_next_features(status)["blocked"]
    for feature in blocked:
        project = campaign.feature_project(feature["feature_id"])
        ledger.append(
            actor="campaign",
            kind="feature_status",
            payload={
                "campaign_id": campaign_id,
                "project_id": project.project_id,
                "feature_id": feature["feature_id"],
                "status": "blocked",
                "reason": feature["reason"],
            },
        )


async def run_campaign_round(
    ledger: Ledger,
    campaign: Campaign,
    executor: Executor,
    *,
    max_parallel: int = 6,
    budget: int | None = None,
    gates: GatePolicy | None = None,
    resume: bool = False,
) -> dict[str, str]:
    """Dispatch one best-effort round of a campaign. The only new async surface.

    Reduces status, picks runnable forum-owned features (up to ``budget``),
    witnesses a campaign_dispatch{wave}, builds a Plan whose Tasks are exactly
    those features (their deps are already done, so a single wave), and awaits
    dispatch_plan REUSED verbatim (inheriting gates, best-effort within-wave
    handling, and witnessing). For each result, appends feature_status done (with
    witnessed_seq at the real result) if ok else failed (reason=output). A failed
    feature does NOT halt the round or the campaign. Appends a campaign_result
    snapshot and syncs. Returns {feature_id: status} for the features it acted on.
    """
    status = derive_campaign_status(ledger, campaign.campaign_id)
    runnable = derive_next_features(status)["runnable"]
    if budget is not None:
        runnable = runnable[:budget]

    if not runnable:
        # Nothing to run this round; still surface any newly-blocked dependents.
        _witness_blocked(ledger, campaign, campaign.campaign_id)
        return {}

    wave_ids = [f["feature_id"] for f in runnable]
    ledger.append(
        actor="campaign",
        kind="campaign_dispatch",
        payload={"campaign_id": campaign.campaign_id, "wave": wave_ids, "budget": budget},
    )

    # Build a Plan of exactly these features. Their deps are already done, so they
    # carry no intra-plan depends_on: one wave. done_when criteria ride along.
    tasks = tuple(
        Task(
            id=feature["feature_id"],
            agent=_feature_agent(campaign, feature["feature_id"]),
            instruction=_feature_instruction(campaign, feature["feature_id"]),
            done_when=_feature_done_when(campaign, feature["feature_id"]),
        )
        for feature in runnable
    )
    plan = Plan(tasks)
    results = await dispatch_plan(
        plan, ledger, executor, max_parallel=max_parallel, resume=resume, gates=gates
    )

    acted: dict[str, str] = {}
    for feature in runnable:
        fid = feature["feature_id"]
        result = results.get(fid)
        if result is None:
            # not run this round (e.g. paused at a gate before this wave); leave it.
            continue
        project = campaign.feature_project(fid)
        if result.ok:
            ledger.append(
                actor="campaign",
                kind="feature_status",
                payload={
                    "campaign_id": campaign.campaign_id,
                    "project_id": project.project_id,
                    "feature_id": fid,
                    "status": "done",
                    "reason": "",
                    "witnessed_seq": result.witnessed_seq,
                },
            )
            acted[fid] = "done"
        else:
            ledger.append(
                actor="campaign",
                kind="feature_status",
                payload={
                    "campaign_id": campaign.campaign_id,
                    "project_id": project.project_id,
                    "feature_id": fid,
                    "status": "failed",
                    "reason": result.output,
                    "witnessed_seq": result.witnessed_seq,
                },
            )
            acted[fid] = "failed"

    # Surface dependents newly blocked by this round's failures, then snapshot.
    _witness_blocked(ledger, campaign, campaign.campaign_id)
    _campaign_result_snapshot(ledger, campaign.campaign_id)
    ledger.sync()
    return acted


async def run_campaign(
    ledger: Ledger,
    campaign: Campaign,
    executor: Executor,
    *,
    max_parallel: int = 6,
    budget: int | None = None,
    gates: GatePolicy | None = None,
) -> dict[str, str]:
    """Loop run_campaign_round until no feature is runnable (a fixed point).

    Best-effort: stops when nothing is RUNNABLE, not when something failed. A dep
    chain advances one wave per round; a failed feature blocks its dependents but
    does not stop the loop. Returns the merged {feature_id: status} of every round.
    """
    acted: dict[str, str] = {}
    while True:
        status = derive_campaign_status(ledger, campaign.campaign_id)
        runnable = derive_next_features(status)["runnable"]
        if not runnable:
            break
        round_acted = await run_campaign_round(
            ledger, campaign, executor,
            max_parallel=max_parallel, budget=budget, gates=gates,
        )
        if not round_acted:
            # No feature completed this round (e.g. paused at a gate); stop to
            # avoid an infinite loop. The operator resolves and re-invokes.
            break
        acted.update(round_acted)
    return acted


def _feature_agent(campaign: Campaign, feature_id: str) -> str:
    return _find_feature(campaign, feature_id).agent


def _feature_instruction(campaign: Campaign, feature_id: str) -> str:
    return _find_feature(campaign, feature_id).instruction


def _feature_done_when(campaign: Campaign, feature_id: str) -> tuple[str, ...]:
    return _find_feature(campaign, feature_id).done_when


def _find_feature(campaign: Campaign, feature_id: str):
    project = campaign.feature_project(feature_id)
    for feature in project.features:
        if feature.feature_id == feature_id:
            return feature
    raise KeyError(feature_id)
