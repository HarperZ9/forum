from __future__ import annotations

from collections import Counter

from forum.ledger import Ledger


def summarize(ledger: Ledger) -> dict:
    """Aggregate a witnessed ledger into a run summary, from the record itself.

    Counts entries by kind, task results (and failures), verdict pass/fail,
    escalations, budget stops, contexts, synthesized answers, and model calls per
    model (read from each task result's recorded model). Pure and read-only:
    everything comes from what was witnessed, so the summary is as trustworthy as
    the ledger it reads.
    """
    entries = ledger.replay()
    kinds: Counter[str] = Counter(e.kind for e in entries)

    model_calls: Counter[str] = Counter()
    task_results = 0
    failed_results = 0
    answers = 0
    for e in ledger.query(kind="result"):
        body = ledger.get_payload(e.payload_hash)
        if "answer" in body:
            answers += 1
            continue
        task_results += 1
        model = body.get("model")
        if model:
            model_calls[model] += 1
        if body.get("ok") is False:
            failed_results += 1

    verdicts = ledger.query(kind="verdict")
    verdicts_pass = sum(1 for v in verdicts if ledger.get_payload(v.payload_hash).get("ok"))

    return {
        "entries": len(entries),
        "requests": kinds.get("request", 0),
        "plans": kinds.get("plan", 0),
        "tasks": kinds.get("task", 0),
        "task_results": task_results,
        "failed_results": failed_results,
        "verdicts_pass": verdicts_pass,
        "verdicts_fail": len(verdicts) - verdicts_pass,
        "escalations": kinds.get("tier_escalation", 0),
        "budget_stops": kinds.get("budget", 0),
        "contexts": kinds.get("context", 0),
        "answers": answers,
        "model_calls": dict(model_calls),
        "checkpoint": ledger.checkpoint(),
        "verified": ledger.verify(),
    }


_NUMERIC = (
    "entries", "requests", "plans", "tasks", "task_results", "failed_results",
    "verdicts_pass", "verdicts_fail", "escalations", "budget_stops", "contexts", "answers",
)


def compare(a: dict, b: dict) -> dict:
    """The delta (b - a) of the numeric fields of two summaries, for A/B run comparison."""
    return {k: b.get(k, 0) - a.get(k, 0) for k in _NUMERIC}
