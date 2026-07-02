from __future__ import annotations

from typing import Any

from forum.campaign import campaign_from_payload
from forum.ledger import Ledger

# Feature status values that a feature_status entry may carry.
_STATUS_VALUES = frozenset({"done", "in_progress", "blocked", "failed"})
# The synthetic status the reducer assigns when a done claim is not witnessed.
_UNWITNESSED = "unwitnessed"
_DONE_VIOLATION = "claimed done without witnessing result"

# Statuses that count as a met dependency (only a witnessed done qualifies).
# Deps in any other state (pending / in_progress / blocked / failed / unwitnessed)
# do not satisfy a downstream.


def _result_ok_for(ledger: Ledger, seq: Any, feature_id: str) -> bool:
    """True iff ``seq`` is a real result entry for ``feature_id`` with ok is True.

    The honesty gate: a claimed done is only honored when its witnessed_seq points
    at a genuine successful result for THIS feature. A None/non-int seq, a seq that
    is not a result, a result for another feature, or a result with ok is not True
    all fail. Enforced here at REDUCE time, not at write time.
    """
    if not isinstance(seq, int) or isinstance(seq, bool):
        return False
    try:
        entry = ledger.get(seq)
    except KeyError:
        return False
    if entry.kind != "result":
        return False
    try:
        body = ledger.get_payload(entry.payload_hash)
    except KeyError:
        return False
    if not isinstance(body, dict):
        return False
    return body.get("id") == feature_id and body.get("ok") is True


def _latest_campaign_declared(ledger: Ledger, campaign_id: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for entry in ledger.query(kind="campaign_declared"):
        body = ledger.get_payload(entry.payload_hash)
        if isinstance(body, dict) and body.get("campaign_id") == campaign_id:
            latest = body
    return latest


def _latest_feature_statuses(
    ledger: Ledger, campaign_id: str
) -> dict[str, dict[str, Any]]:
    """Latest-wins-by-seq feature_status payload per feature id, for this campaign."""
    latest: dict[str, dict[str, Any]] = {}
    for entry in ledger.query(kind="feature_status"):
        body = ledger.get_payload(entry.payload_hash)
        if not isinstance(body, dict) or body.get("campaign_id") != campaign_id:
            continue
        fid = body.get("feature_id")
        if isinstance(fid, str):
            latest[fid] = body
    return latest


def derive_campaign_status(ledger: Ledger, campaign_id: str) -> dict[str, Any]:
    """Reduce the ledger into a campaign's current status. Pure, read-only.

    Scans the latest campaign_declared to rebuild structure, folds latest-wins
    feature_status entries into current state, and applies the honesty gate: a
    feature_status{done} is only honored when its witnessed_seq points at a real
    successful result FOR THAT feature; otherwise it becomes ``unwitnessed`` with a
    violation and is NOT counted as done. Status is never stored, only reduced.
    """
    declared = _latest_campaign_declared(ledger, campaign_id)
    if declared is None:
        raise KeyError(f"no campaign_declared for {campaign_id!r}")
    campaign = campaign_from_payload(declared)
    statuses = _latest_feature_statuses(ledger, campaign_id)

    # First pass: resolve each feature's own status (honesty gate applied to done).
    resolved: dict[str, dict[str, Any]] = {}
    for project in campaign.projects:
        for feature in project.features:
            fid = feature.feature_id
            body = statuses.get(fid)
            status = "pending"
            reason = ""
            witnessed_seq: Any = None
            violation: str | None = None
            external = project.owner != "forum"
            if body is not None:
                raw_status = body.get("status")
                reason = str(body.get("reason", ""))
                witnessed_seq = body.get("witnessed_seq")
                source = body.get("source")
                if raw_status == "done":
                    if external and source:
                        # An external system reported done; forum did not witness a
                        # result for it. Honored as done but labeled distinctly,
                        # never a violation and never blessed as forum-verified.
                        status = "done"
                    elif _result_ok_for(ledger, witnessed_seq, fid):
                        status = "done"
                    else:
                        status = _UNWITNESSED
                        violation = _DONE_VIOLATION
                elif raw_status in _STATUS_VALUES:
                    status = raw_status
                else:
                    status = "pending"
            resolved[fid] = {
                "feature_id": fid,
                "project_id": project.project_id,
                "owner": project.owner,
                "priority": feature.priority,
                "depends_on": list(feature.depends_on),
                "status": status,
                "reason": reason,
                "witnessed_seq": witnessed_seq,
                "external": external,
                "external_source": (
                    body.get("source") if body is not None else None
                ),
            }
            if violation is not None:
                resolved[fid]["violation"] = violation

    # Second pass: dependency satisfaction (a dep is met only if it is done).
    features_out: list[dict[str, Any]] = []
    for fid, entry in resolved.items():
        blocking: list[str] = []
        for dep in entry["depends_on"]:
            dep_entry = resolved.get(dep)
            if dep_entry is None or dep_entry["status"] != "done":
                blocking.append(dep)
        entry["deps_met"] = not blocking
        entry["blocking_deps"] = blocking
        features_out.append(entry)

    counts = {
        "done": 0, "in_progress": 0, "blocked": 0,
        "failed": 0, "pending": 0, "unwitnessed": 0,
    }
    for entry in features_out:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1

    # Complete when every FORUM-owned feature is done and no violations exist.
    # External features are not forum-executable, so they never block completeness;
    # a campaign with only external work left is complete on the forum side.
    forum_features = [f for f in features_out if not f["external"]]
    no_violations = not any("violation" in f for f in features_out)
    complete = (
        bool(forum_features)
        and all(f["status"] == "done" for f in forum_features)
        and no_violations
    )

    projects_out = [
        {
            "project_id": p.project_id,
            "owner": p.owner,
            "priority": p.priority,
            "feature_ids": [f.feature_id for f in p.features],
        }
        for p in campaign.projects
    ]

    return {
        "campaign_id": campaign.campaign_id,
        "title": campaign.title,
        "complete": complete,
        "counts": counts,
        "features": features_out,
        "projects": projects_out,
    }


def _blocked_reason(feature: dict[str, Any], features_by_id: dict[str, dict[str, Any]]) -> str:
    bad: list[str] = []
    for dep in feature["blocking_deps"]:
        dep_entry = features_by_id.get(dep)
        dep_status = dep_entry["status"] if dep_entry else "unknown"
        if dep_status in {"failed", "blocked", _UNWITNESSED}:
            bad.append(f"{dep} is {dep_status}")
    if bad:
        return "blocked: " + ", ".join(bad)
    return "waiting on: " + ", ".join(feature["blocking_deps"])


def derive_next_features(status: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Split pending features into runnable vs blocked. Pure.

    runnable = a forum-owned, still-pending feature whose deps are all done, sorted
    priority desc then feature_id. blocked = a pending feature whose dep is
    failed / blocked / unwitnessed (surfaced with a reason). External-owned features
    are NEVER runnable (forum does not execute them).
    """
    features = status["features"]
    features_by_id = {f["feature_id"]: f for f in features}
    runnable: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for feature in features:
        if feature["status"] != "pending":
            continue
        if feature["external"]:
            continue
        bad_dep = any(
            (features_by_id.get(dep) or {}).get("status") in {"failed", "blocked", _UNWITNESSED}
            for dep in feature["blocking_deps"]
        )
        if bad_dep:
            blocked.append({**feature, "reason": _blocked_reason(feature, features_by_id)})
        elif feature["deps_met"]:
            runnable.append(feature)
        # else: waiting on a still-pending/in_progress dep; neither runnable nor
        # surfaced as blocked (it will become runnable once the dep completes).
    runnable.sort(key=lambda f: (-int(f["priority"]), f["feature_id"]))
    blocked.sort(key=lambda f: f["feature_id"])
    return {"runnable": runnable, "blocked": blocked}
