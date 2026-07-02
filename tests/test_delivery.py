import asyncio

from forum.delivery import assess
from forum.engine import Orchestrator
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.report import summarize
from forum.roster import loads

# ---- the deterministic delivery floor ---------------------------------------------


def test_assess_terse_text_is_not_flagged():
    d = assess("Ship the API. Add tests. Done.")
    assert d.flagged is False
    assert d.words > 0 and d.sentences == 3


def test_assess_flags_long_sentences():
    d = assess(" ".join(["word"] * 50) + ".")  # one 50-word sentence
    assert d.mean_sentence_words > 30
    assert d.flagged is True


def test_assess_flags_filler():
    d = assess("Honestly it is really very basically just actually quite simply done.")
    assert d.filler_ratio > 0.06
    assert d.flagged is True


def test_assess_empty_text_is_not_flagged():
    d = assess("")
    assert d.flagged is False
    assert d.words == 0


# ---- the verified-tighten ladder in a run -----------------------------------------

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

REQUEST = "build the login api and the schema"
# flagged by filler, and it covers login/api/schema
VERBOSE = "Honestly it is really very basically just actually quite simply the login api and the schema."
# tighter and still covers login/api/schema -> a revision Forum will accept
REVISED = "the login api and the schema"


class _Exec:
    def __init__(self, answer: str) -> None:
        self._answer = answer
        self.assignments = []

    async def run(self, a):
        self.assignments.append(a)
        agent = a.agent
        if agent == "coordinator":
            return Result(a.task_id, agent, '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build", "depends_on": []}]}')
        if agent == "validator":
            return Result(a.task_id, agent, '{"ok": true, "score": 0.9, "reason": "ok"}')
        if agent == "synthesizer":
            return Result(a.task_id, agent, self._answer)
        return Result(a.task_id, agent, "did it")


class _Reviser:
    def __init__(self, revised):
        self._revised = revised

    def revise(self, request, answer):
        return self._revised


def _led():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _orch(led, answer, **kw):
    return Orchestrator(
        ROSTER, led, _Exec(answer),
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2),
        **kw,
    )


def _orch_with_executor(led, executor, **kw):
    return Orchestrator(
        ROSTER, led, executor,
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2),
        **kw,
    )


def test_floor_always_runs_and_default_has_no_reviser():
    led = _led()
    asyncio.run(_orch(led, VERBOSE).submit(REQUEST))  # default NullReviser
    assert len(led.query(kind="delivery_check")) == 1      # the floor always runs
    assert led.query(kind="revision") == []                # default abstains, no revision


def test_flagged_answer_is_tightened_and_the_revision_is_delivered():
    led = _led()
    answer = asyncio.run(_orch(led, VERBOSE, reviser=_Reviser(REVISED)).submit(REQUEST))
    assert answer == REVISED  # the tighter, verified revision replaces the verbose answer
    rev = led.get_payload(led.query(kind="revision")[0].payload_hash)
    assert rev["accepted"] is True
    assert rev["words_after"] < rev["words_before"]
    assert rev["coverage_after"] >= rev["coverage_before"]


def test_a_revision_that_drops_coverage_is_rejected():
    led = _led()
    # "done" is tighter but loses the request's terms -> rejected, original kept
    answer = asyncio.run(_orch(led, VERBOSE, reviser=_Reviser("done")).submit(REQUEST))
    assert answer == VERBOSE
    assert led.get_payload(led.query(kind="revision")[0].payload_hash)["accepted"] is False


def test_terse_answer_is_not_revised_even_with_a_reviser():
    led = _led()
    asyncio.run(_orch(led, "Built the login api and the schema.", reviser=_Reviser(REVISED)).submit(REQUEST))
    assert led.query(kind="revision") == []  # not flagged -> the reviser is not pulled
    assert len(led.query(kind="delivery_check")) == 1


def test_reviser_crash_is_witnessed_not_fatal():
    led = _led()

    class _Boom:
        def revise(self, request, answer):
            raise RuntimeError("reviser down")

    answer = asyncio.run(_orch(led, VERBOSE, reviser=_Boom()).submit(REQUEST))
    assert answer == VERBOSE  # the answer survives a crashing reviser
    assert led.get_payload(led.query(kind="revision")[0].payload_hash)["accepted"] is False
    assert led.verify(deep=True) is True


def test_summary_reports_delivery_and_revisions():
    led = _led()
    asyncio.run(_orch(led, VERBOSE, reviser=_Reviser(REVISED)).submit(REQUEST))
    s = summarize(led)
    assert s["delivery_checks"] == 1 and s["delivery_flagged"] == 1
    assert s["revisions"] == 1 and s["revisions_accepted"] == 1


def test_revision_and_verifier_chain_to_the_delivered_answer():
    from forum.verify import Verification

    class _V:
        def verify(self, request, answer):
            return Verification(ok=True, detail="checked", source="v")

    led = _led()
    answer = asyncio.run(_orch(led, VERBOSE, reviser=_Reviser(REVISED), verifier=_V()).submit(REQUEST))
    assert answer == REVISED
    v = led.query(kind="verification")[0]
    parent = led.get(v.causal_parent)  # verification must chain to the DELIVERED answer
    assert led.get_payload(parent.payload_hash).get("answer") == REVISED


def test_a_longer_or_identical_revision_is_rejected():
    led = _led()
    asyncio.run(_orch(led, VERBOSE, reviser=_Reviser(VERBOSE + " plus several more words")).submit(REQUEST))
    assert led.get_payload(led.query(kind="revision")[0].payload_hash)["accepted"] is False
    led2 = _led()
    asyncio.run(_orch(led2, VERBOSE, reviser=_Reviser(VERBOSE)).submit(REQUEST))  # identical: not strictly shorter
    assert led2.get_payload(led2.query(kind="revision")[0].payload_hash)["accepted"] is False


def test_accepted_revision_is_a_result_entry_and_answers_counts_once():
    led = _led()
    asyncio.run(_orch(led, VERBOSE, reviser=_Reviser(REVISED)).submit(REQUEST))
    bodies = [led.get_payload(e.payload_hash) for e in led.query(kind="result")]
    assert any(b.get("answer") == REVISED for b in bodies)  # the delivered revision is a result entry
    assert summarize(led)["answers"] == 1                    # but the run still counts one logical answer


def test_submit_witnesses_delivery_profile_check():
    led = _led()
    answer = asyncio.run(
        _orch(led, "The module passes the focused test from the ledger. Ship the API.").submit(
            REQUEST,
            delivery_profile="engineer",
        )
    )
    assert "Ship the API" in answer
    entries = led.query(kind="delivery_profile_check")
    assert len(entries) == 1
    payload = led.get_payload(entries[0].payload_hash)
    assert payload["schema"] == "forum.delivery-profile/v1"
    assert payload["profile"] == "engineer"
    assert payload["flagged"] is False
    parent = led.get(entries[0].causal_parent)
    assert led.get_payload(parent.payload_hash).get("answer") == answer
    assert led.verify(deep=True) is True


def test_submit_uses_route_frame_delivery_profile_by_default():
    led = _led()
    answer = asyncio.run(
        _orch(led, "The module passes the focused test from the ledger. Ship the API.").submit(
            "build eval gated model promotion for a self improving daemon"
        )
    )
    route_frame = led.query(kind="route_frame")
    assert len(route_frame) == 1
    frame = led.get_payload(route_frame[0].payload_hash)
    assert frame["schema"] == "forum.route-frame/v1"
    assert frame["domain"] == "model-foundry"
    assert frame["delivery_profile"] == "engineer"
    entries = led.query(kind="delivery_profile_check")
    assert len(entries) == 1
    payload = led.get_payload(entries[0].payload_hash)
    assert payload["profile"] == "engineer"
    assert payload["flagged"] is False
    parent = led.get(entries[0].causal_parent)
    assert led.get_payload(parent.payload_hash).get("answer") == answer


def test_explicit_delivery_profile_overrides_route_frame():
    led = _led()
    asyncio.run(
        _orch(led, "Ship the model review.").submit(
            "build eval gated model promotion for a self improving daemon",
            delivery_profile="operator",
        )
    )
    frame = led.get_payload(led.query(kind="route_frame")[0].payload_hash)
    assert frame["delivery_profile"] == "engineer"
    payload = led.get_payload(led.query(kind="delivery_profile_check")[0].payload_hash)
    assert payload["profile"] == "operator"


def test_submit_passes_route_frame_contract_to_synthesizer():
    led = _led()
    executor = _Exec("The module passes the focused test from the ledger. Ship the API.")
    asyncio.run(
        _orch_with_executor(led, executor).submit(
            "build eval gated model promotion for a self improving daemon"
        )
    )
    synth = next(a for a in executor.assignments if a.agent == "synthesizer")
    assert "Delivery contract:" in synth.instruction
    assert "posture=architect" in synth.instruction
    assert "profile=engineer" in synth.instruction
    assert "domain=model-foundry" in synth.instruction
    assert "gating evidence" in synth.instruction


def test_delivery_profile_check_chains_to_accepted_revision():
    led = _led()
    answer = asyncio.run(
        _orch(led, VERBOSE, reviser=_Reviser(REVISED)).submit(
            REQUEST,
            delivery_profile="operator",
        )
    )
    assert answer == REVISED
    check = led.query(kind="delivery_profile_check")[0]
    parent = led.get(check.causal_parent)
    assert led.get_payload(parent.payload_hash).get("answer") == REVISED


def test_unknown_delivery_profile_fails_before_ledger_write():
    led = _led()
    try:
        asyncio.run(_orch(led, "answer").submit(REQUEST, delivery_profile="poet"))
    except ValueError as exc:
        assert "unknown delivery profile" in str(exc)
    else:
        raise AssertionError("expected ValueError")
    assert led.replay() == []


def test_assess_counts_non_ascii_words():
    d = assess("café build the relational schema")
    assert d.words == 5  # unicode-aware tokenization keeps non-ascii words
