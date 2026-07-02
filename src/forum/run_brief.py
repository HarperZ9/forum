from __future__ import annotations

BRIEF_SCHEMA = "forum.run-room.brief/v1"

_ATTENTION_SIGNAL_KEYS = (
    "budget_stops",
    "failed_results",
    "failed_verdicts",
    "flagged_delivery",
    "flagged_delivery_profiles",
    "flagged_intent",
    "refuted_verifications",
)


def build_room_brief(room: dict) -> dict:
    request = room.get("request") or {}
    route_frame = room.get("route_frame") or {}
    state = _brief_state(room)
    subject = _brief_subject(request)
    return {
        "schema": BRIEF_SCHEMA,
        "state": state,
        "title": _brief_title(state, subject),
        "posture": route_frame.get("posture") or "operator",
        "delivery_profile": route_frame.get("delivery_profile") or "operator",
        "summary": _brief_summary(state, bool(room.get("verified", False))),
        "risk": _brief_risk(room),
        "next_step": _brief_next_step(room, state),
        "bullets": _brief_bullets(room),
    }


def room_brief_text(room: dict) -> str:
    brief = room.get("brief") or build_room_brief(room)
    lines = [
        "Forum operator brief",
        f"Status: {_state_label(str(brief.get('state', 'ready')))}",
        (
            f"Posture: {brief.get('posture', 'operator')} / "
            f"{brief.get('delivery_profile', 'operator')}"
        ),
        "",
        str(brief.get("title", "")),
        str(brief.get("summary", "")),
        f"Risk: {brief.get('risk', '')}",
        f"Next: {brief.get('next_step', '')}",
    ]
    bullets = brief.get("bullets") or []
    if bullets:
        lines.extend(["", "Signals:"])
        lines.extend(f"- {bullet}" for bullet in bullets)
    return "\n".join(lines)


def _brief_state(room: dict) -> str:
    if not room.get("request"):
        return "idle"
    signals = room.get("signals") or {}
    if not room.get("verified", False):
        return "action_required"
    if any((action.get("priority") == "high") for action in room.get("next_actions") or []):
        return "action_required"
    if any(signals.get(key, 0) > 0 for key in _ATTENTION_SIGNAL_KEYS):
        return "action_required"
    if (room.get("answer") or {}).get("text"):
        return "complete"
    if room.get("tasks"):
        return "in_progress"
    return "ready"


def _brief_subject(request: dict) -> str:
    return str(request.get("text") or "current run")


def _brief_title(state: str, subject: str) -> str:
    if state == "idle":
        return "No active run"
    if state == "action_required":
        return f"Action required: {subject}"
    if state == "complete":
        return f"Run complete: {subject}"
    if state == "in_progress":
        return f"Run in progress: {subject}"
    return f"Run ready: {subject}"


def _brief_summary(state: str, verified: bool) -> str:
    if state == "idle":
        return "No run has been submitted in this room yet."
    if state == "action_required":
        if verified:
            return "The latest run is verified but needs operator attention before delivery."
        return "The latest run needs operator attention because ledger verification failed."
    if state == "complete":
        return "The latest run is verified, has a final answer, and has no blocking signals."
    if state == "in_progress":
        return "The latest run is verified and still in progress; no final answer is present yet."
    return "The latest request is witnessed and ready for planning or execution."


def _brief_risk(room: dict) -> str:
    if not room.get("verified", False):
        return "Ledger verification failed; inspect the record before acting."
    signals = room.get("signals") or {}
    execution = []
    if signals.get("failed_results", 0) > 0:
        execution.append(_count_phrase(signals["failed_results"], "failed result"))
    if signals.get("failed_verdicts", 0) > 0:
        execution.append(_count_phrase(signals["failed_verdicts"], "failed verdict"))
    if execution:
        return f"Execution has {_join_phrase(execution)}."
    if signals.get("budget_stops", 0) > 0:
        return f"Budget stopped the run {_count_phrase(signals['budget_stops'], 'time')}."
    if signals.get("refuted_verifications", 0) > 0:
        return "External verification refuted the answer."
    delivery = []
    if signals.get("flagged_delivery", 0) > 0:
        delivery.append(_count_phrase(signals["flagged_delivery"], "delivery check"))
    if signals.get("flagged_delivery_profiles", 0) > 0:
        delivery.append(
            _count_phrase(signals["flagged_delivery_profiles"], "delivery profile check")
        )
    if delivery:
        return f"Delivery needs review: {_join_phrase(delivery)} flagged."
    if signals.get("flagged_intent", 0) > 0:
        return "Intent coverage flagged possible drift."
    return "No blocking signals detected."


def _brief_next_step(room: dict, state: str) -> str:
    actions = room.get("next_actions") or []
    if actions:
        label = actions[0].get("label") or actions[0].get("kind") or "Review room"
        return _sentence(str(label))
    if state == "idle":
        return "Submit a request."
    if state == "ready":
        return "Create and submit the task plan."
    if state == "in_progress":
        return "Continue execution until a final answer is witnessed."
    return "Review the room."


def _brief_bullets(room: dict) -> list[str]:
    route_frame = room.get("route_frame") or {}
    tasks = room.get("tasks") or []
    results = sum(1 for task in tasks if task.get("result"))
    accepted = sum(1 for task in tasks if (task.get("verdict") or {}).get("ok") is True)
    route = "Route: not witnessed"
    if route_frame:
        route = (
            "Route: "
            f"{route_frame.get('domain', '')} / "
            f"{route_frame.get('intent', '')} / "
            f"{route_frame.get('posture', '')}"
        )
    return [
        route,
        f"Tasks: {len(tasks)} total, {results} with results, {accepted} accepted",
        f"Answer: {'present' if (room.get('answer') or {}).get('text') else 'missing'}",
    ]


def _state_label(state: str) -> str:
    return state.replace("_", " ").capitalize()


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _count_phrase(count: int, singular: str) -> str:
    return f"{count} {singular if count == 1 else singular + 's'}"


def _join_phrase(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return f"{', '.join(parts[:-1])}, and {parts[-1]}"
