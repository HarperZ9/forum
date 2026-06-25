import asyncio

from forum.engine import Orchestrator
from forum.executor import Result
from forum.intent import coverage, salient_terms
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.roster import loads

# ---- the pure coverage primitives -------------------------------------------------


def test_salient_terms_drops_stopwords_and_short_tokens():
    assert salient_terms("Build the login API now") == {"build", "login", "api", "now"}
    assert salient_terms("a b cd") == {"cd"}  # single chars dropped, "cd" kept


def test_salient_terms_is_case_and_punctuation_insensitive():
    assert salient_terms("Login, API!") == salient_terms("login api")


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
    """A scripted control loop whose synthesized answer is fixed per test."""

    def __init__(self, answer: str) -> None:
        self._answer = answer

    async def run(self, a):
        agent = a.agent
        if agent == "coordinator":
            return Result(a.task_id, agent, '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build the api", "depends_on": []}]}')
        if agent == "validator":
            return Result(a.task_id, agent, '{"ok": true, "score": 0.9, "reason": "ok"}')
        if agent == "synthesizer":
            return Result(a.task_id, agent, self._answer)
        return Result(a.task_id, agent, "did it")


def _led():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _orch(led, answer, **kw):
    return Orchestrator(
        ROSTER, led, _Exec(answer),
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
