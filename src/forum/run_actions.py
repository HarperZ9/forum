from __future__ import annotations


def derive_next_actions(
    *,
    request: dict | None,
    tasks: list[dict],
    checkpoints: list[dict],
    answer: dict | None,
    signals: dict[str, int],
    pending_gates: list[dict] | None = None,
) -> list[dict]:
    if request is None:
        return [_submit_request_action()]

    high = _blocking_actions(tasks, checkpoints, answer, signals)
    high.extend(_gate_actions(pending_gates or []))
    normal = _quality_actions(signals)
    if answer is not None and not high:
        normal.append(_export_action(answer))
    return high + normal


def _gate_actions(pending_gates: list[dict]) -> list[dict]:
    """A high-priority review action per pending human-in-the-loop gate.

    A gate pauses the run until the operator resolves it, so it is a blocking
    action: nothing downstream runs until it is approved, edited, or rejected.
    """
    actions: list[dict] = []
    for gate in pending_gates:
        run_seq = gate.get("run_seq")
        wave = gate.get("wave")
        actions.append(
            _action(
                f"review-gate:{run_seq}:{wave}",
                "review_gate",
                "high",
                f"Review gate on wave {wave}",
                "a wave is paused awaiting human approval",
                {"run_seq": run_seq, "wave": wave},
            )
        )
    return actions


def _submit_request_action() -> dict:
    return _action(
        "submit-request",
        "submit_request",
        "normal",
        "Submit a request",
        "room has no request",
        {},
    )


def _blocking_actions(
    tasks: list[dict],
    checkpoints: list[dict],
    answer: dict | None,
    signals: dict[str, int],
) -> list[dict]:
    actions = _retry_actions(tasks)
    if signals.get("budget_stops", 0) > 0:
        actions.append(_budget_action())
    if checkpoints and answer is None:
        actions.append(_resume_action(checkpoints[-1]))
    return actions


def _budget_action() -> dict:
    return _action(
        "raise-budget",
        "raise_budget",
        "high",
        "Raise or revise run budget",
        "run stopped on budget",
        {},
    )


def _resume_action(checkpoint: dict) -> dict:
    return _action(
        "resume-from-checkpoint",
        "resume_from_checkpoint",
        "high",
        "Resume from latest checkpoint",
        "checkpoint exists and no answer is present",
        {"checkpoint_seq": checkpoint.get("seq"), "wave": checkpoint.get("wave")},
    )


def _export_action(answer: dict) -> dict:
    return _action(
        "export-receipt",
        "export_receipt",
        "normal",
        "Export run receipt",
        "answer is present and no blocking signals were detected",
        {"answer_seq": answer.get("seq")},
    )


def _retry_actions(tasks: list[dict]) -> list[dict]:
    actions: list[dict] = []
    seen: set[str] = set()
    for task in tasks:
        task_id = str(task.get("id", ""))
        if not task_id or task_id in seen:
            continue
        result = task.get("result") or {}
        verdict = task.get("verdict") or {}
        if result.get("ok") is False:
            actions.append(
                _action(
                    f"retry-task:{task_id}",
                    "retry_task",
                    "high",
                    f"Retry {task_id}",
                    "latest task result failed",
                    {"task_id": task_id, "result_seq": result.get("seq")},
                )
            )
            seen.add(task_id)
        elif verdict.get("ok") is False:
            actions.append(
                _action(
                    f"retry-task:{task_id}",
                    "retry_task",
                    "high",
                    f"Retry {task_id}",
                    "latest task verdict failed",
                    {"task_id": task_id, "task_seq": task.get("seq")},
                )
            )
            seen.add(task_id)
    return actions


def _quality_actions(signals: dict[str, int]) -> list[dict]:
    actions: list[dict] = []
    if signals.get("flagged_delivery", 0) > 0 or signals.get("flagged_delivery_profiles", 0) > 0:
        actions.append(
            _action(
                "revise-delivery",
                "revise_delivery",
                "normal",
                "Review or revise delivery",
                "delivery checks flagged the answer",
                {},
            )
        )
    if signals.get("flagged_intent", 0) > 0:
        actions.append(
            _action(
                "judge-intent",
                "judge_intent",
                "normal",
                "Judge answer intent",
                "intent floor flagged possible drift",
                {},
            )
        )
    if signals.get("refuted_verifications", 0) > 0:
        actions.append(
            _action(
                "review-verification",
                "review_verification",
                "normal",
                "Review verifier refutation",
                "external verification refuted the answer",
                {},
            )
        )
    return actions


def _action(
    action_id: str,
    kind: str,
    priority: str,
    label: str,
    reason: str,
    target: dict,
) -> dict:
    return {
        "id": action_id,
        "kind": kind,
        "priority": priority,
        "label": label,
        "reason": reason,
        "target": target,
    }
