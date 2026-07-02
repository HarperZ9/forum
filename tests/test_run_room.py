from forum.ledger import InMemoryStorage, Ledger
from forum.run_room import RUN_ROOM_SCHEMA, build_run_room, room_text


def _ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def test_build_run_room_joins_current_run_state():
    led = _ledger()
    req = led.append(actor="client", kind="request", payload={"text": "build the api with tests"})
    led.append(
        actor="router",
        kind="route_frame",
        payload={
            "schema": "forum.route-frame/v1",
            "domain": "implementation",
            "intent": "execute",
            "posture": "architect",
            "delivery_profile": "engineer",
        },
        causal_parent=req.seq,
    )
    plan = led.append(
        actor="dispatch",
        kind="plan",
        payload={"waves": [["T1"]], "edges": []},
        causal_parent=req.seq,
    )
    task = led.append(
        actor="dispatch",
        kind="task",
        payload={
            "id": "T1",
            "agent": "backend",
            "instruction": "build api",
            "data_from": [],
            "done_when": ["tests pass"],
        },
        causal_parent=plan.seq,
    )
    result = led.append(
        actor="backend",
        kind="result",
        payload={
            "id": "T1",
            "output": "abcdefghijklmnop",
            "ok": True,
            "model": "local",
        },
        causal_parent=task.seq,
    )
    led.append(
        actor="validator",
        kind="verdict",
        payload={"id": "T1", "ok": True, "score": 0.9, "reason": "ok"},
        causal_parent=result.seq,
    )
    led.append(
        actor="dispatch",
        kind="checkpoint",
        payload={"wave": 0, "root": "abc123"},
        causal_parent=plan.seq,
    )
    led.append(
        actor="context-budget",
        kind="context_budget",
        payload={"original_tokens": 10, "admitted_tokens": 4, "action": "trimmed"},
        causal_parent=task.seq,
    )
    answer = led.append(
        actor="synthesizer",
        kind="result",
        payload={"answer": "final answer with implementation detail"},
        causal_parent=req.seq,
    )
    led.append(
        actor="delivery-profile",
        kind="delivery_profile_check",
        payload={"profile": "engineer", "flagged": False},
        causal_parent=answer.seq,
    )

    room = build_run_room(led, max_text_chars=12)

    assert room["schema"] == RUN_ROOM_SCHEMA
    assert room["verified"] is True
    assert room["entry_range"] == [req.seq, led.replay()[-1].seq]
    assert room["request"]["text"] == "build the..."
    assert room["route_frame"]["domain"] == "implementation"
    assert room["plan"]["waves"] == [["T1"]]
    assert room["tasks"] == [
        {
            "seq": task.seq,
            "id": "T1",
            "agent": "backend",
            "instruction": "build api",
            "done_when": ["tests pass"],
            "data_from": [],
            "result": {
                "seq": result.seq,
                "ok": True,
                "model": "local",
                "output": "abcdefghi...",
            },
            "verdict": {"ok": True, "score": 0.9, "reason": "ok"},
        }
    ]
    assert room["checkpoints"] == [{"seq": 6, "wave": 0, "root": "abc123"}]
    assert room["answer"]["text"] == "final ans..."
    assert room["signals"]["context_tokens_saved"] == 6
    assert room["signals"]["delivery_profile_checks"] == 1
    assert room["next_actions"] == [
        {
            "id": "export-receipt",
            "kind": "export_receipt",
            "priority": "normal",
            "label": "Export run receipt",
            "reason": "answer is present and no blocking signals were detected",
            "target": {"answer_seq": answer.seq},
        }
    ]
    assert "Forum run room" in room_text(room)


def test_build_run_room_defaults_to_latest_request():
    led = _ledger()
    led.append(actor="client", kind="request", payload={"text": "old request"})
    led.append(actor="dispatch", kind="task", payload={"id": "old", "agent": "backend", "instruction": "old"})
    latest = led.append(actor="client", kind="request", payload={"text": "new request"})
    led.append(actor="dispatch", kind="task", payload={"id": "new", "agent": "backend", "instruction": "new"})

    room = build_run_room(led)

    assert room["entry_range"][0] == latest.seq
    assert room["request"]["text"] == "new request"
    assert [task["id"] for task in room["tasks"]] == ["new"]


def test_run_room_next_actions_retry_failed_task_once():
    led = _ledger()
    req = led.append(actor="client", kind="request", payload={"text": "fix failing parser"})
    plan = led.append(
        actor="dispatch",
        kind="plan",
        payload={"waves": [["T1"]], "edges": []},
        causal_parent=req.seq,
    )
    task = led.append(
        actor="dispatch",
        kind="task",
        payload={"id": "T1", "agent": "backend", "instruction": "fix parser"},
        causal_parent=plan.seq,
    )
    result = led.append(
        actor="backend",
        kind="result",
        payload={"id": "T1", "output": "boom", "ok": False, "model": "local"},
        causal_parent=task.seq,
    )
    led.append(
        actor="validator",
        kind="verdict",
        payload={"id": "T1", "ok": False, "score": 0.1, "reason": "failed"},
        causal_parent=result.seq,
    )

    room = build_run_room(led)

    assert [action["kind"] for action in room["next_actions"]].count("retry_task") == 1
    assert room["next_actions"][0] == {
        "id": "retry-task:T1",
        "kind": "retry_task",
        "priority": "high",
        "label": "Retry T1",
        "reason": "latest task result failed",
        "target": {"task_id": "T1", "result_seq": result.seq},
    }


def test_run_room_next_actions_surface_quality_and_resume_signals():
    led = _ledger()
    req = led.append(actor="client", kind="request", payload={"text": "finish the release"})
    plan = led.append(
        actor="dispatch",
        kind="plan",
        payload={"waves": [["T1"]], "edges": []},
        causal_parent=req.seq,
    )
    led.append(
        actor="dispatch",
        kind="checkpoint",
        payload={"wave": 1, "root": "root123"},
        causal_parent=plan.seq,
    )
    led.append(
        actor="budget",
        kind="budget",
        payload={"reason": "run stopped on budget"},
        causal_parent=req.seq,
    )
    led.append(
        actor="delivery-profile",
        kind="delivery_profile_check",
        payload={"profile": "engineer", "flagged": True},
        causal_parent=req.seq,
    )
    led.append(
        actor="intent-floor",
        kind="intent_check",
        payload={"flagged": True},
        causal_parent=req.seq,
    )
    led.append(
        actor="verifier",
        kind="verification",
        payload={"ok": False, "reason": "refuted"},
        causal_parent=req.seq,
    )

    room = build_run_room(led)

    assert [action["kind"] for action in room["next_actions"]] == [
        "raise_budget",
        "resume_from_checkpoint",
        "revise_delivery",
        "judge_intent",
        "review_verification",
    ]
