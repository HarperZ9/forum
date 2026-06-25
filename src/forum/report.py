from __future__ import annotations

import json
from collections import Counter

from forum.ledger import Ledger


def summarize(ledger: Ledger) -> dict:
    """Aggregate a witnessed ledger into a run summary, from the record itself.

    Counts entries by kind, task results (and failures), verdict pass/fail,
    intent-coverage checks (and how many were flagged, judged, and judged as
    drift), external verifications (and how many were refuted), escalations, budget
    stops, contexts, synthesized answers, model calls per model with a scalar total
    (read from each task result's recorded model), and the byte weight of the
    witnessed payloads (an efficiency signal, comparable across runs). Pure and
    read-only: everything comes from what was witnessed, so the summary is as
    trustworthy as the ledger it reads.
    """
    entries = ledger.replay()
    kinds: Counter[str] = Counter(e.kind for e in entries)

    model_calls: Counter[str] = Counter()
    task_results = 0
    failed_results = 0
    answers = 0
    for e in ledger.query(kind="result"):
        body = ledger.get_payload(e.payload_hash)
        # A kind="result" entry is one of two things, told apart positively by the
        # keys the engine writes: a task result always carries the task "id" (from
        # the dispatcher, an escalation retry, and submit_one), while the synthesized
        # final answer carries "answer" alone. Keying on "id" (not on the absence of
        # "answer") keeps the count right even if a task's own output ever included
        # an "answer" field.
        if "id" in body:
            task_results += 1
            model = body.get("model")
            if model:
                model_calls[model] += 1
            if body.get("ok") is False:
                failed_results += 1
        elif "answer" in body:
            answers += 1

    verdicts = ledger.query(kind="verdict")
    verdicts_pass = sum(1 for v in verdicts if ledger.get_payload(v.payload_hash).get("ok"))

    intent_checks = ledger.query(kind="intent_check")
    intent_flagged = sum(1 for e in intent_checks if ledger.get_payload(e.payload_hash).get("flagged"))
    intent_judgments = ledger.query(kind="intent_judgment")
    intent_drift_judged = sum(
        1 for e in intent_judgments if ledger.get_payload(e.payload_hash).get("ok") is False
    )
    verifications = ledger.query(kind="verification")
    verifications_refuted = sum(
        1 for e in verifications if ledger.get_payload(e.payload_hash).get("ok") is False
    )

    # The UTF-8 byte weight of the witnessed content (distinct payloads; the content
    # store already dedups identical bodies). An efficiency signal, not a token count:
    # a leaner run carries a lighter record, and forum bench shows whether a change
    # reduced it. Encoded to bytes (like canonical_hash) so the count is true bytes,
    # not codepoints, for non-ascii content.
    seen: set[str] = set()
    payload_bytes = 0
    for e in entries:
        if e.payload_hash in seen:
            continue
        seen.add(e.payload_hash)
        try:
            body = ledger.get_payload(e.payload_hash)
        except KeyError:
            continue
        payload_bytes += len(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8"))

    return {
        "entries": len(entries),
        "requests": kinds.get("request", 0),
        "plans": kinds.get("plan", 0),
        "tasks": kinds.get("task", 0),
        "task_results": task_results,
        "failed_results": failed_results,
        "verdicts_pass": verdicts_pass,
        "verdicts_fail": len(verdicts) - verdicts_pass,
        "intent_checks": len(intent_checks),
        "intent_flagged": intent_flagged,
        "intent_judgments": len(intent_judgments),
        "intent_drift_judged": intent_drift_judged,
        "verifications": len(verifications),
        "verifications_refuted": verifications_refuted,
        "checkpoints": kinds.get("checkpoint", 0),
        "resumes": kinds.get("resume", 0),
        "escalations": kinds.get("tier_escalation", 0),
        "budget_stops": kinds.get("budget", 0),
        "contexts": kinds.get("context", 0),
        "answers": answers,
        "model_calls": dict(model_calls),
        # scalar total so a model-call change flows through compare()/bench; equals
        # task_results in a normal run (every task result records its model).
        "model_calls_total": sum(model_calls.values()),
        "payload_bytes": payload_bytes,
        "checkpoint": ledger.checkpoint(),
        "verified": ledger.verify(),
    }


_NUMERIC = (
    "entries", "requests", "plans", "tasks", "task_results", "failed_results",
    "verdicts_pass", "verdicts_fail", "intent_checks", "intent_flagged",
    "intent_judgments", "intent_drift_judged", "verifications", "verifications_refuted",
    "checkpoints", "resumes",
    "escalations", "budget_stops", "contexts", "answers", "model_calls_total",
    "payload_bytes",
)


def compare(a: dict, b: dict) -> dict:
    """The delta (b - a) of the numeric fields of two summaries, for A/B run comparison."""
    return {k: b.get(k, 0) - a.get(k, 0) for k in _NUMERIC}
