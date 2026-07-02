from __future__ import annotations

from typing import Any

from forum.campaign_status import derive_campaign_status, derive_next_features
from forum.ledger import Ledger

CAMPAIGN_ROOM_SCHEMA = "forum.campaign-room/v1"


def _action(
    action_id: str, kind: str, priority: str, label: str, reason: str, target: dict
) -> dict[str, Any]:
    return {
        "id": action_id,
        "kind": kind,
        "priority": priority,
        "label": label,
        "reason": reason,
        "target": target,
    }


def derive_campaign_next_actions(status: dict[str, Any]) -> list[dict[str, Any]]:
    """Operator next actions for a campaign, same _action shape as run_actions.

    - each unwitnessed/violation feature -> a high-priority investigate action
    - the highest-priority runnable feature -> a dispatch_feature action
    - each blocked feature -> an unblock action carrying its reason
    - a complete campaign -> a close_campaign action
    """
    actions: list[dict[str, Any]] = []

    # Highest priority: fabricated / unwitnessed done claims.
    for feature in status["features"]:
        if "violation" in feature:
            fid = feature["feature_id"]
            actions.append(
                _action(
                    f"investigate:{fid}",
                    "investigate",
                    "high",
                    f"Investigate {fid}",
                    feature["violation"],
                    {"feature_id": fid, "project_id": feature["project_id"]},
                )
            )

    nxt = derive_next_features(status)
    runnable = nxt["runnable"]
    if runnable:
        top = runnable[0]  # already sorted priority desc, feature_id
        actions.append(
            _action(
                f"dispatch-feature:{top['feature_id']}",
                "dispatch_feature",
                "high",
                f"Dispatch {top['feature_id']}",
                "highest-priority runnable feature",
                {"feature_id": top["feature_id"], "project_id": top["project_id"]},
            )
        )

    for feature in nxt["blocked"]:
        fid = feature["feature_id"]
        actions.append(
            _action(
                f"unblock:{fid}",
                "unblock",
                "high",
                f"Unblock {fid}",
                feature["reason"],
                {"feature_id": fid, "project_id": feature["project_id"]},
            )
        )

    if status["complete"]:
        actions.append(
            _action(
                f"close-campaign:{status['campaign_id']}",
                "close_campaign",
                "normal",
                "Close the campaign",
                "every forum-owned feature is witnessed done",
                {"campaign_id": status["campaign_id"]},
            )
        )

    return actions


def build_campaign_room(ledger: Ledger, campaign_id: str) -> dict[str, Any]:
    """Project a campaign into an operator room snapshot.

    derive_campaign_status + checkpoint + verify(deep=True) + a progress signal +
    next actions. Read-only.
    """
    status = derive_campaign_status(ledger, campaign_id)
    counts = status["counts"]
    total = sum(counts.values())
    progress = {
        "done": counts["done"],
        "total": total,
        "failed": counts["failed"],
        "blocked": counts["blocked"],
        "unwitnessed": counts["unwitnessed"],
        "pending": counts["pending"],
        "in_progress": counts["in_progress"],
    }
    return {
        "schema": CAMPAIGN_ROOM_SCHEMA,
        "campaign_id": status["campaign_id"],
        "title": status["title"],
        "checkpoint": ledger.checkpoint(),
        "verified": ledger.verify(deep=True),
        "complete": status["complete"],
        "counts": counts,
        "progress": progress,
        "features": status["features"],
        "projects": status["projects"],
        "next_actions": derive_campaign_next_actions(status),
    }


def campaign_room_text(room: dict[str, Any]) -> str:
    lines = [
        f"Forum campaign room: {room.get('campaign_id', '')}",
        f"title: {room.get('title', '')}",
        f"checkpoint: {room.get('checkpoint', '')}",
        f"verified: {room.get('verified', False)}",
        f"complete: {room.get('complete', False)}",
    ]
    progress = room.get("progress") or {}
    lines.append(
        f"progress: {progress.get('done', 0)}/{progress.get('total', 0)} done "
        f"(failed {progress.get('failed', 0)}, blocked {progress.get('blocked', 0)}, "
        f"unwitnessed {progress.get('unwitnessed', 0)})"
    )
    actions = room.get("next_actions") or []
    if actions:
        lines.append("next actions:")
        for action in actions:
            lines.append(
                f"- {action.get('priority', '')}/{action.get('kind', '')}: "
                f"{action.get('label', '')} ({action.get('reason', '')})"
            )
    return "\n".join(lines)
