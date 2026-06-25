import asyncio

from forum.budget import RunBudget
from forum.control import IntentJudge
from forum.engine import Orchestrator
from forum.executor import Result
from forum.intent import coverage, salient_terms
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.report import summarize
from forum.roster import loads

# ---- the pure coverage primitives -------------------------------------------------


def test_salient_terms_drops_stopwords_and_short_tokens():
    assert salient_terms("Build the login API now") == {"build", "login", "api", "now"}
    assert salient_terms("a b cd") == {"cd"}  # single chars dropped, "cd" kept


def test_salient_terms_is_case_and_punctuation_insensitive():
    assert salient_terms("Login, API!") == salient_terms("login api")


def test_salient_terms_keeps_non_ascii_words():
    # Unicode-aware: non-Latin scripts and accented words are kept, not silently dropped
    assert salient_terms("café Москва") == {"café", "москва"}


def test_salient_terms_splits_snake_case():
    assert salient_terms("build_login_api") == {"build", "login", "api"}


def test_coverage_full_when_answer_carries_all_terms():
    score, missing = coverage("build the login api", "build login api endpoint shipped")
    assert score == 1.0
    assert missing == set()


def test_coverage_partial_lists_the_missing_terms():
    score, missing = coverage("build the login api", "shipped the login")
    assert score == 1 / 3            # of {build, login, api}, only login is present
    assert missing == {"build", "api"}


def test_coverage_zero_when_nothing_overlaps():
    score, missing = coverage("build the login api", "done")
    assert score == 0.0
    assert missing == {"build", "login", "api"}


def test_empty_request_is_fully_covered():
    # a content-free request never reads as drift
    score, missing = coverage("the a of to", "anything at all")
    assert score == 1.0
    assert missing == set()


# ---- the witnessed intent check in a run ------------------------------------------

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


class _Exec:
    """A scripted control loop whose synthesized answer (and judge verdict) are fixed."""

    def __init__(self, answer: str, judge_ok: bool = True) -> None:
        self._answer = answer
        self._judge_ok = judge_ok

    async def run(self, a):
        agent = a.agent
        if agent == "coordinator":
            return Result(a.task_id, agent, '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build the api", "depends_on": []}]}')
        if agent == "validator":
            return Result(a.task_id, agent, '{"ok": true, "score": 0.9, "reason": "ok"}')
        if agent == "intent-judge":
            return Result(a.task_id, agent, '{"ok": %s, "score": 0.8, "reason": "judged"}' % ("true" if self._judge_ok else "false"))
        if agent == "synthesizer":
            return Result(a.task_id, agent, self._answer)
        return Result(a.task_id, agent, "did it")


def _led():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _orch(led, answer, judge_ok=True, **kw):
    return Orchestrator(
        ROSTER, led, _Exec(answer, judge_ok),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2),
        **kw,
    )


def test_submit_witnesses_one_intent_check_chained_to_the_answer():
    led = _led()
    asyncio.run(_orch(led, "the api endpoint is built and shipped").submit("build the api"))
    checks = led.query(kind="intent_check")
    assert len(checks) == 1
    parent = led.get(checks[0].causal_parent)  # chained to the synthesized answer
    assert parent.kind == "result" and "answer" in led.get_payload(parent.payload_hash)


def test_intent_not_flagged_when_the_answer_covers_the_request():
    led = _led()
    asyncio.run(_orch(led, "build the api works").submit("build the api"))
    body = led.get_payload(led.query(kind="intent_check")[0].payload_hash)
    assert body["coverage"] == 1.0          # both of {build, api} are present
    assert body["flagged"] is False
    assert body["missing"] == []


def test_intent_flagged_when_the_answer_drifts():
    led = _led()
    asyncio.run(_orch(led, "done").submit("build the api"))
    body = led.get_payload(led.query(kind="intent_check")[0].payload_hash)
    assert body["coverage"] == 0.0
    assert body["flagged"] is True
    assert body["missing"] == ["api", "build"]   # sorted, for a stable record


def test_intent_threshold_is_configurable():
    led = _led()
    asyncio.run(_orch(led, "the api", intent_threshold=0.6).submit("build the api"))
    body = led.get_payload(led.query(kind="intent_check")[0].payload_hash)
    assert body["coverage"] == 0.5               # covers api, misses build
    assert body["flagged"] is True               # 0.5 < 0.6


def test_run_stays_deep_verifiable_with_the_intent_check():
    led = _led()
    asyncio.run(_orch(led, "done").submit("build the api"))
    assert led.verify(deep=True) is True


def test_intent_coverage_is_rounded_and_marked_lexical_in_the_payload():
    led = _led()
    asyncio.run(_orch(led, "the api").submit("build the login api"))
    body = led.get_payload(led.query(kind="intent_check")[0].payload_hash)
    assert body["coverage"] == 0.3333          # 1 of {build, login, api}, rounded to 4 dp
    assert body["method"] == "lexical_coverage"


def test_intent_run_is_reproducible_across_runs():
    # identical witnessed runs hash identically, the rounded intent payload included;
    # this is what makes the new entry replay-stable
    a, b = _led(), _led()
    asyncio.run(_orch(a, "the api").submit("build the login api"))
    asyncio.run(_orch(b, "the api").submit("build the login api"))
    assert a.checkpoint() == b.checkpoint()


def test_no_intent_check_on_a_budget_stopped_run():
    # the budget-stop path returns a canned answer; intent-checking it would manufacture
    # a meaningless flag, so the run carries no intent_check
    led = _led()
    asyncio.run(_orch(led, "done").submit("build the api", budget=RunBudget(max_model_calls=0)))
    assert led.query(kind="intent_check") == []


# ---- the model intent-judge (the rung above the floor) ----------------------------


def test_flagged_run_with_a_judge_witnesses_an_intent_judgment():
    led = _led()
    asyncio.run(_orch(led, "done", intent_judge=IntentJudge()).submit("build the api"))
    judged = led.query(kind="intent_judgment")
    assert len(judged) == 1
    parent = led.get(judged[0].causal_parent)
    assert parent.kind == "intent_check"   # the judgment resolves the floor's flag


def test_judge_clears_a_lexical_false_positive():
    led = _led()
    asyncio.run(_orch(led, "done", judge_ok=True, intent_judge=IntentJudge()).submit("build the api"))
    body = led.get_payload(led.query(kind="intent_judgment")[0].payload_hash)
    assert body["ok"] is True


def test_judge_confirms_real_drift():
    led = _led()
    asyncio.run(_orch(led, "done", judge_ok=False, intent_judge=IntentJudge()).submit("build the api"))
    body = led.get_payload(led.query(kind="intent_judgment")[0].payload_hash)
    assert body["ok"] is False


def test_no_judgment_when_coverage_passes_even_with_a_judge():
    led = _led()
    # the answer covers the request, so the floor never flags and the judge is not spent
    asyncio.run(_orch(led, "build the api works", intent_judge=IntentJudge()).submit("build the api"))
    assert led.query(kind="intent_judgment") == []


def test_no_judgment_without_a_judge():
    led = _led()
    asyncio.run(_orch(led, "done").submit("build the api"))   # no intent_judge configured
    assert led.query(kind="intent_judgment") == []


def test_judge_skipped_when_budget_is_spent_by_synthesis():
    # the run completes normally (plan, task, validate, synthesize = 4 calls), so the
    # floor still runs, but the budget is exhausted by synthesis, so the judge is skipped
    led = _led()
    asyncio.run(
        _orch(led, "done", intent_judge=IntentJudge()).submit("build the api", budget=RunBudget(max_model_calls=4))
    )
    assert len(led.query(kind="intent_check")) == 1
    assert led.query(kind="intent_judgment") == []


def test_summary_reports_judgments_and_confirmed_drift():
    led = _led()
    asyncio.run(_orch(led, "done", judge_ok=False, intent_judge=IntentJudge()).submit("build the api"))
    s = summarize(led)
    assert s["intent_judgments"] == 1
    assert s["intent_drift_confirmed"] == 1
    assert led.verify(deep=True) is True
