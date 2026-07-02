import asyncio
from pathlib import Path

from forum.engine import Orchestrator
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.report import compare, summarize
from forum.roster import loads

ROSTER = loads(
    """
[[agent]]
name="backend"
category="engineering"
domain="apis"
keywords=["api"]
model_tier="capable"
executor="echo"
"""
)


def test_flagship_brand_assets_exist_and_are_referenced():
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    for rel in [
        "docs/brand/forum-mark.svg",
        "docs/brand/forum-hero.png",
        "examples/forum-demo.html",
    ]:
        assert (root / rel).exists(), rel
        assert rel in readme
    assert (root / "docs/brand/forum-hero.svg").exists()
    assert "## Why it matters" in readme
    assert "## Work with it" in readme
    demo = (root / "examples/forum-demo.html").read_text(encoding="utf-8")
    assert "deep verification catches body tampering" in demo
    assert "Skip to content" in demo


class _Exec:
    async def run(self, a):
        agent = a.agent
        if agent == "coordinator":
            return Result(a.task_id, agent, '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build", "depends_on": []}]}')
        if agent == "validator":
            return Result(a.task_id, agent, '{"ok": true, "score": 0.9, "reason": "ok"}')
        if agent == "synthesizer":
            return Result(a.task_id, agent, "final")
        return Result(a.task_id, agent, "did it")


class _FailExec:
    """Like _Exec, but the backend task fails (ok=False), so it is never validated."""

    async def run(self, a):
        agent = a.agent
        if agent == "coordinator":
            return Result(a.task_id, agent, '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build", "depends_on": []}]}')
        if agent == "synthesizer":
            return Result(a.task_id, agent, "final")
        # the task output contains the word "answer"; it must still count as a task
        # result, not be mistaken for the synthesized answer
        return Result(a.task_id, agent, "answer: none", ok=False)


def _led():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _run(led):
    orch = Orchestrator(ROSTER, led, _Exec(), Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2))
    asyncio.run(orch.submit("build the api"))


def _run_failing(led):
    orch = Orchestrator(ROSTER, led, _FailExec(), Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2))
    asyncio.run(orch.submit("build the api"))


def test_get_payload_public_accessor():
    led = _led()
    e = led.append(actor="x", kind="k", payload={"v": 1})
    assert led.get_payload(e.payload_hash) == {"v": 1}


def test_summarize_counts_a_witnessed_run():
    led = _led()
    _run(led)
    s = summarize(led)
    assert s["requests"] == 1
    assert s["tasks"] == 1
    assert s["task_results"] == 1
    assert s["failed_results"] == 0
    assert s["verdicts_pass"] == 1 and s["verdicts_fail"] == 0
    assert s["answers"] == 1
    assert s["intent_checks"] == 1
    assert s["intent_flagged"] == 1   # the scripted answer "final" misses "build"/"api"
    assert s["escalations"] == 0
    assert s["model_calls"] == {"_Exec": 1}   # the executor's identity, seen through the counter
    assert s["model_calls_total"] == 1
    assert s["verified"] is True
    assert len(s["checkpoint"]) == 64


def test_summary_reports_payload_weight():
    led = _led()
    _run(led)
    s = summarize(led)
    assert s["payload_bytes"] > 0
    assert summarize(_led())["payload_bytes"] == 0   # an empty ledger weighs nothing
    assert "payload_bytes" in compare(s, s)          # flows through bench


def test_payload_weight_grows_with_content():
    small, big = _led(), _led()
    small.append(actor="x", kind="result", payload={"id": "T", "output": "ok", "model": "m"})
    big.append(actor="x", kind="result", payload={"id": "T", "output": "z" * 5000, "model": "m"})
    assert summarize(big)["payload_bytes"] > summarize(small)["payload_bytes"]


def test_payload_bytes_counts_utf8_bytes_not_codepoints():
    led = _led()
    led.append(actor="x", kind="result", payload={"id": "T", "output": "\u5b57" * 100, "model": "m"})
    # the output is 100 codepoints but 300 UTF-8 bytes; payload_bytes must reflect bytes
    assert summarize(led)["payload_bytes"] >= 300


def test_compare_two_runs_reports_deltas():
    a_led, b_led = _led(), _led()
    _run(a_led)
    _run(b_led)
    _run(b_led)  # b has two runs
    delta = compare(summarize(a_led), summarize(b_led))
    assert delta["requests"] == 1          # b has one more request than a
    assert delta["task_results"] == 1
    assert delta["answers"] == 1
    assert delta["model_calls_total"] == 1


def test_summarize_counts_a_failed_run():
    led = _led()
    _run_failing(led)
    s = summarize(led)
    assert s["task_results"] == 1
    assert s["failed_results"] == 1            # the executor returned ok=False
    assert s["verdicts_fail"] == 1 and s["verdicts_pass"] == 0
    assert s["answers"] == 1                   # the synthesizer still writes one answer
    assert s["model_calls_total"] == 1         # the failed task still recorded its model


def test_failed_vs_clean_run_compares():
    good, bad = _led(), _led()
    _run(good)
    _run_failing(bad)
    delta = compare(summarize(good), summarize(bad))
    assert delta["failed_results"] == 1        # bad has one more failed task result
    assert delta["verdicts_fail"] == 1
    assert delta["verdicts_pass"] == -1        # and one fewer pass


def test_task_result_with_an_answer_key_is_still_a_task_result():
    # The discriminator keys on the task "id", not the absence of "answer", so a task
    # result that carries an "answer" field is not mistaken for the synthesized answer.
    led = _led()
    led.append(actor="backend", kind="result", payload={"id": "T1", "output": "x", "ok": True, "model": "m", "answer": "sneaky"})
    led.append(actor="synthesizer", kind="result", payload={"answer": "the real final answer"})
    s = summarize(led)
    assert s["task_results"] == 1
    assert s["answers"] == 1
    assert s["model_calls"] == {"m": 1}


def test_summary_reports_context_pressure_metrics():
    led = _led()
    led.append(
        actor="context-budget",
        kind="context_budget",
        payload={
            "schema": "forum.context-pressure/v1",
            "source": "task",
            "label": "T1",
            "action": "trimmed",
            "reason": "max_task_tokens",
            "original_bytes": 40,
            "admitted_bytes": 20,
            "original_tokens": 10,
            "admitted_tokens": 5,
            "remaining_total_tokens": 20,
        },
    )
    led.append(
        actor="context-budget",
        kind="context_budget",
        payload={
            "schema": "forum.context-pressure/v1",
            "source": "task",
            "label": "T2",
            "action": "omitted",
            "reason": "max_total_tokens",
            "original_bytes": 16,
            "admitted_bytes": 0,
            "original_tokens": 4,
            "admitted_tokens": 0,
            "remaining_total_tokens": 0,
        },
    )
    s = summarize(led)
    assert s["context_budget_checks"] == 2
    assert s["context_budget_trimmed"] == 1
    assert s["context_budget_omitted"] == 1
    assert s["context_tokens_original"] == 14
    assert s["context_tokens_admitted"] == 5
    assert s["context_tokens_saved"] == 9
    assert "context_tokens_saved" in compare(s, s)


def test_summary_reports_delivery_profile_metrics():
    led = _led()
    led.append(
        actor="delivery-profile",
        kind="delivery_profile_check",
        payload={
            "schema": "forum.delivery-profile/v1",
            "profile": "engineer",
            "words": 9,
            "sentences": 1,
            "mean_sentence_words": 9.0,
            "filler_ratio": 0.0,
            "flagged": False,
            "findings": [],
        },
    )
    led.append(
        actor="delivery-profile",
        kind="delivery_profile_check",
        payload={
            "schema": "forum.delivery-profile/v1",
            "profile": "executive",
            "words": 140,
            "sentences": 2,
            "mean_sentence_words": 70.0,
            "filler_ratio": 0.0,
            "flagged": True,
            "findings": [{"code": "too_many_words", "detail": "word count 140 exceeds 120"}],
        },
    )
    s = summarize(led)
    assert s["delivery_profile_checks"] == 2
    assert s["delivery_profile_flagged"] == 1
    assert s["delivery_profile_engineer"] == 1
    assert s["delivery_profile_executive"] == 1
    assert s["delivery_profile_operator"] == 0
    assert s["delivery_profile_researcher"] == 0
    assert "delivery_profile_flagged" in compare(s, s)
