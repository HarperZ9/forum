from __future__ import annotations

from collections import Counter
from typing import Any

from forum.ledger import Ledger

CONTEXT_CAPSULE_SCHEMA = "forum.context-capsule/v1"


def build_context_capsule(
    ledger: Ledger,
    *,
    max_items: int = 8,
    max_text_chars: int = 240,
) -> dict:
    if max_items < 0:
        raise ValueError("max_items must be >= 0")
    if max_text_chars < 0:
        raise ValueError("max_text_chars must be >= 0")

    entries = ledger.replay()
    counts = Counter(entry.kind for entry in entries)
    payloads = [(entry, _payload(ledger, entry.payload_hash)) for entry in entries]
    capsule = {
        "schema": CONTEXT_CAPSULE_SCHEMA,
        "checkpoint": ledger.checkpoint(),
        "verified": ledger.verify(),
        "entry_range": [entries[0].seq, entries[-1].seq] if entries else [None, None],
        "counts": dict(counts),
        "latest_request": _latest_request(payloads, max_text_chars),
        "latest_answer": _latest_answer(payloads, max_text_chars),
        "tasks": _tasks(payloads, max_items, max_text_chars),
        "signals": _signals(payloads, counts),
    }
    capsule["context_text_chars"] = len(capsule_text(capsule))
    return capsule


def capsule_text(capsule: dict) -> str:
    lines = [
        "Forum context capsule",
        f"checkpoint: {capsule.get('checkpoint', '')}",
        f"verified: {capsule.get('verified', False)}",
    ]
    request = capsule.get("latest_request") or ""
    answer = capsule.get("latest_answer") or ""
    if request:
        lines.append(f"latest request: {request}")
    if answer:
        lines.append(f"latest answer: {answer}")
    tasks = capsule.get("tasks") or []
    if tasks:
        lines.append("tasks:")
        for task in tasks:
            lines.append(
                f"- {task.get('id', '')}/{task.get('agent', '')} "
                f"ok={task.get('ok')} model={task.get('model', '')}: "
                f"{task.get('output', '')}"
            )
    signals = capsule.get("signals") or {}
    if signals:
        ordered = " ".join(f"{key}={signals[key]}" for key in sorted(signals))
        lines.append(f"signals: {ordered}")
    return "\n".join(lines)


class LedgerCapsuleProvider:
    def __init__(
        self,
        ledger: Ledger,
        *,
        max_items: int = 8,
        max_text_chars: int = 240,
    ) -> None:
        self._ledger = ledger
        self._max_items = max_items
        self._max_text_chars = max_text_chars

    def context(self, request: str) -> str:
        capsule = build_context_capsule(
            self._ledger,
            max_items=self._max_items,
            max_text_chars=self._max_text_chars,
        )
        return capsule_text(capsule)


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


def _latest_request(payloads: list[tuple[Any, dict[str, Any]]], max_text_chars: int) -> str:
    for entry, payload in reversed(payloads):
        if entry.kind == "request" and isinstance(payload.get("text"), str):
            return _clip(payload["text"], max_text_chars)
    return ""


def _latest_answer(payloads: list[tuple[Any, dict[str, Any]]], max_text_chars: int) -> str:
    for entry, payload in reversed(payloads):
        if entry.kind == "result" and isinstance(payload.get("answer"), str):
            return _clip(payload["answer"], max_text_chars)
    return ""


def _tasks(
    payloads: list[tuple[Any, dict[str, Any]]],
    max_items: int,
    max_text_chars: int,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for entry, payload in payloads:
        if entry.kind != "result" or "id" not in payload:
            continue
        tasks.append({
            "seq": entry.seq,
            "id": str(payload.get("id", "")),
            "agent": str(payload.get("agent", entry.actor)),
            "ok": payload.get("ok"),
            "model": str(payload.get("model", "")),
            "output": _clip(payload.get("output", ""), max_text_chars),
        })
    if max_items == 0:
        return []
    return tasks[-max_items:]


def _signals(payloads: list[tuple[Any, dict[str, Any]]], counts: Counter[str]) -> dict[str, int]:
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
