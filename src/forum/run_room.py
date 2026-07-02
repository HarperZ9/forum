from __future__ import annotations

from collections import Counter
from typing import Any

from forum.ledger import Ledger, LedgerEntry
from forum.run_actions import derive_next_actions

RUN_ROOM_SCHEMA = "forum.run-room/v1"


def build_run_room(
    ledger: Ledger,
    *,
    since_seq: int | None = None,
    max_text_chars: int = 240,
) -> dict:
    if max_text_chars < 0:
        raise ValueError("max_text_chars must be >= 0")

    all_entries = ledger.replay()
    start_seq = _room_start(all_entries, since_seq)
    entries = [entry for entry in all_entries if start_seq is None or entry.seq >= start_seq]
    payloads = [(entry, _payload(ledger, entry.payload_hash)) for entry in entries]
    counts = Counter(entry.kind for entry in entries)
    request = _request(payloads, max_text_chars)
    route_frame = _latest_kind(payloads, "route_frame")
    plan = _plan(payloads)
    tasks = _tasks(payloads, max_text_chars)
    checkpoints = _checkpoints(payloads)
    answer = _answer(payloads, max_text_chars)
    signals = _signals(payloads, counts)
    return {
        "schema": RUN_ROOM_SCHEMA,
        "checkpoint": ledger.checkpoint(),
        "verified": ledger.verify(deep=True),
        "entry_range": [entries[0].seq, entries[-1].seq] if entries else [None, None],
        "counts": dict(counts),
        "request": request,
        "route_frame": route_frame,
        "plan": plan,
        "tasks": tasks,
        "checkpoints": checkpoints,
        "answer": answer,
        "signals": signals,
        "next_actions": derive_next_actions(
            request=request,
            tasks=tasks,
            checkpoints=checkpoints,
            answer=answer,
            signals=signals,
        ),
    }


def room_text(room: dict) -> str:
    lines = [
        "Forum run room",
        f"checkpoint: {room.get('checkpoint', '')}",
        f"verified: {room.get('verified', False)}",
    ]
    request = room.get("request") or {}
    if request.get("text"):
        lines.append(f"request: {request['text']}")
    route_frame = room.get("route_frame") or {}
    if route_frame:
        lines.append(
            "route: "
            f"{route_frame.get('domain', '')}/"
            f"{route_frame.get('intent', '')}/"
            f"{route_frame.get('posture', '')}"
        )
    tasks = room.get("tasks") or []
    if tasks:
        lines.append("tasks:")
        for task in tasks:
            result = task.get("result") or {}
            verdict = task.get("verdict") or {}
            lines.append(
                f"- {task.get('id', '')}/{task.get('agent', '')} "
                f"result_ok={result.get('ok')} verdict_ok={verdict.get('ok')}: "
                f"{result.get('output', '')}"
            )
    answer = room.get("answer") or {}
    if answer.get("text"):
        lines.append(f"answer: {answer['text']}")
    next_actions = room.get("next_actions") or []
    if next_actions:
        lines.append("next actions:")
        for action in next_actions:
            lines.append(
                f"- {action.get('priority', '')}/{action.get('kind', '')}: "
                f"{action.get('label', '')}"
            )
    return "\n".join(lines)


def _room_start(entries: list[LedgerEntry], since_seq: int | None) -> int | None:
    if since_seq is not None:
        return since_seq
    for entry in reversed(entries):
        if entry.kind == "request":
            return entry.seq
    return entries[0].seq if entries else None


def _payload(ledger: Ledger, payload_hash: str) -> dict[str, Any]:
    try:
        payload = ledger.get_payload(payload_hash)
    except KeyError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _clip(value: Any, max_chars: int) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_chars:
        return text
    if max_chars == 0:
        return ""
    if max_chars <= 3:
        return "." * max_chars
    return text[: max_chars - 3] + "..."


def _request(payloads: list[tuple[LedgerEntry, dict[str, Any]]], max_text_chars: int) -> dict | None:
    for entry, payload in reversed(payloads):
        if entry.kind != "request":
            continue
        result = {"seq": entry.seq}
        if "text" in payload:
            result["text"] = _clip(payload.get("text", ""), max_text_chars)
        if "tasks" in payload:
            result["tasks"] = list(payload.get("tasks") or [])
        return result
    return None


def _latest_kind(payloads: list[tuple[LedgerEntry, dict[str, Any]]], kind: str) -> dict | None:
    for entry, payload in reversed(payloads):
        if entry.kind == kind:
            return dict(payload)
    return None


def _plan(payloads: list[tuple[LedgerEntry, dict[str, Any]]]) -> dict | None:
    for entry, payload in reversed(payloads):
        if entry.kind == "plan":
            return {
                "seq": entry.seq,
                "waves": payload.get("waves", []),
                "edges": payload.get("edges", []),
            }
    return None


def _tasks(payloads: list[tuple[LedgerEntry, dict[str, Any]]], max_text_chars: int) -> list[dict]:
    results = _latest_by_id(payloads, "result")
    verdicts = _latest_by_id(payloads, "verdict")
    tasks: list[dict] = []
    for entry, payload in payloads:
        if entry.kind != "task":
            continue
        task_id = str(payload.get("id", ""))
        task = {
            "seq": entry.seq,
            "id": task_id,
            "agent": str(payload.get("agent", "")),
            "instruction": _clip(payload.get("instruction", ""), max_text_chars),
            "done_when": list(payload.get("done_when") or []),
            "data_from": list(payload.get("data_from") or []),
        }
        result_entry, result = results.get(task_id, (None, None))
        if result_entry is not None and result is not None:
            task["result"] = {
                "seq": result_entry.seq,
                "ok": result.get("ok"),
                "model": str(result.get("model", "")),
                "output": _clip(result.get("output", ""), max_text_chars),
            }
        verdict_entry, verdict = verdicts.get(task_id, (None, None))
        if verdict_entry is not None and verdict is not None:
            task["verdict"] = {
                "ok": verdict.get("ok"),
                "score": verdict.get("score"),
                "reason": _clip(verdict.get("reason", ""), max_text_chars),
            }
        tasks.append(task)
    return tasks


def _latest_by_id(
    payloads: list[tuple[LedgerEntry, dict[str, Any]]], kind: str
) -> dict[str, tuple[LedgerEntry, dict[str, Any]]]:
    latest: dict[str, tuple[LedgerEntry, dict[str, Any]]] = {}
    for entry, payload in payloads:
        if entry.kind != kind or "id" not in payload:
            continue
        latest[str(payload.get("id", ""))] = (entry, payload)
    return latest


def _checkpoints(payloads: list[tuple[LedgerEntry, dict[str, Any]]]) -> list[dict]:
    checkpoints: list[dict] = []
    for entry, payload in payloads:
        if entry.kind != "checkpoint":
            continue
        checkpoints.append({
            "seq": entry.seq,
            "wave": payload.get("wave"),
            "root": str(payload.get("root", "")),
        })
    return checkpoints


def _answer(payloads: list[tuple[LedgerEntry, dict[str, Any]]], max_text_chars: int) -> dict | None:
    for entry, payload in reversed(payloads):
        if entry.kind == "result" and isinstance(payload.get("answer"), str):
            return {"seq": entry.seq, "text": _clip(payload["answer"], max_text_chars)}
    return None


def _signals(payloads: list[tuple[LedgerEntry, dict[str, Any]]], counts: Counter[str]) -> dict[str, int]:
    context_budget_payloads = [
        payload for entry, payload in payloads if entry.kind == "context_budget"
    ]
    original = sum(int(payload.get("original_tokens", 0)) for payload in context_budget_payloads)
    admitted = sum(int(payload.get("admitted_tokens", 0)) for payload in context_budget_payloads)
    return {
        "budget_stops": counts.get("budget", 0),
        "context_budget_checks": len(context_budget_payloads),
        "context_tokens_saved": original - admitted,
        "failed_results": sum(
            1 for entry, payload in payloads
            if entry.kind == "result" and "id" in payload and payload.get("ok") is False
        ),
        "failed_verdicts": sum(
            1 for entry, payload in payloads
            if entry.kind == "verdict" and payload.get("ok") is False
        ),
        "flagged_delivery": sum(
            1 for entry, payload in payloads
            if entry.kind == "delivery_check" and payload.get("flagged")
        ),
        "delivery_profile_checks": sum(
            1 for entry, _ in payloads if entry.kind == "delivery_profile_check"
        ),
        "flagged_delivery_profiles": sum(
            1 for entry, payload in payloads
            if entry.kind == "delivery_profile_check" and payload.get("flagged")
        ),
        "flagged_intent": sum(
            1 for entry, payload in payloads
            if entry.kind == "intent_check" and payload.get("flagged")
        ),
        "refuted_verifications": sum(
            1 for entry, payload in payloads
            if entry.kind == "verification" and payload.get("ok") is False
        ),
    }
