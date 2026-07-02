from forum.context_capsule import (
    CONTEXT_CAPSULE_SCHEMA,
    LedgerCapsuleProvider,
    build_context_capsule,
    capsule_text,
)
from forum.ledger import InMemoryStorage, Ledger


def _ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _seed_run():
    led = _ledger()
    led.append(actor="client", kind="request", payload={"text": "build the api"})
    led.append(
        actor="dispatch",
        kind="task",
        payload={"id": "T1", "agent": "backend", "instruction": "build"},
    )
    led.append(
        actor="backend",
        kind="result",
        payload={
            "id": "T1",
            "output": "built api with schema",
            "ok": True,
            "model": "local-small",
        },
    )
    led.append(
        actor="validator",
        kind="verdict",
        payload={"id": "T1", "ok": True, "score": 0.9, "reason": "ok"},
    )
    led.append(actor="synthesizer", kind="result", payload={"answer": "The api is built."})
    led.append(
        actor="intent",
        kind="intent_check",
        payload={"flagged": False, "coverage": 1.0, "missing": []},
    )
    led.append(actor="delivery", kind="delivery_check", payload={"flagged": False, "words": 4})
    led.append(
        actor="context-budget",
        kind="context_budget",
        payload={"original_tokens": 20, "admitted_tokens": 8, "action": "trimmed"},
    )
    return led


def test_capsule_empty_ledger_is_valid():
    capsule = build_context_capsule(_ledger())
    assert capsule["schema"] == CONTEXT_CAPSULE_SCHEMA
    assert capsule["entry_range"] == [None, None]
    assert capsule["latest_request"] == ""
    assert capsule["latest_answer"] == ""
    assert capsule["tasks"] == []
    assert capsule["verified"] is True
    assert len(capsule["checkpoint"]) == 64


def test_capsule_extracts_latest_request_answer_tasks_and_signals():
    led = _seed_run()
    capsule = build_context_capsule(led, max_items=4, max_text_chars=40)
    assert capsule["schema"] == CONTEXT_CAPSULE_SCHEMA
    assert capsule["checkpoint"] == led.checkpoint()
    assert capsule["entry_range"] == [0, 7]
    assert capsule["latest_request"] == "build the api"
    assert capsule["latest_answer"] == "The api is built."
    assert capsule["counts"]["result"] == 2
    assert capsule["tasks"] == [{
        "seq": 2,
        "id": "T1",
        "agent": "backend",
        "ok": True,
        "model": "local-small",
        "output": "built api with schema",
    }]
    assert capsule["signals"]["context_tokens_saved"] == 12
    assert capsule["context_text_chars"] == len(capsule_text(capsule))


def test_capsule_clips_long_text_and_caps_tasks():
    led = _ledger()
    led.append(actor="client", kind="request", payload={"text": "x" * 40})
    for i in range(3):
        led.append(
            actor="worker",
            kind="result",
            payload={"id": f"T{i}", "output": "y" * 40, "ok": True, "model": "m"},
        )
    capsule = build_context_capsule(led, max_items=2, max_text_chars=10)
    assert capsule["latest_request"] == "xxxxxxx..."
    assert [task["id"] for task in capsule["tasks"]] == ["T1", "T2"]
    assert all(task["output"].endswith("...") for task in capsule["tasks"])


def test_capsule_text_is_compact_and_prompt_safe():
    capsule = build_context_capsule(_seed_run())
    text = capsule_text(capsule)
    assert "Forum context capsule" in text
    assert "latest request: build the api" in text
    assert "latest answer: The api is built." in text
    assert "context_tokens_saved=12" in text
    assert len(text) == capsule["context_text_chars"]


def test_ledger_capsule_provider_returns_rendered_capsule():
    led = _seed_run()
    provider = LedgerCapsuleProvider(led)
    text = provider.context("next request")
    assert "Forum context capsule" in text
    assert "latest answer: The api is built." in text
