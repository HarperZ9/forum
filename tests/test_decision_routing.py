"""Decision routing: probabilities, the abstain outcome, calibration and the bench.

Each behaviour is asserted in a pair: the genuine case and a one-change
mutation that must flip the outcome.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from forum.decision_routing import (
    DecisionRouter,
    calibrate_threshold,
    probabilities,
    terms,
)
from forum.decision_routing_bench import abstain_stats, run, split
from forum.roster import load_default, loads

FIXTURE = Path(__file__).parent / "fixtures" / "forum_routing_labels.json"
ROSTER = loads(
    """
[[agent]]
name="backend"
category="engineering"
domain="server side services"
keywords=["api","database","schema"]
model_tier="capable"
executor="cli"

[[agent]]
name="frontend"
category="engineering"
domain="user interfaces"
keywords=["react","css","layout"]
model_tier="capable"
executor="cli"
"""
)


def test_clear_request_is_decided_and_unmatched_request_abstains():
    router = DecisionRouter()
    decided = router.score("design the database schema for the api", ROSTER)
    assert decided.decided == "backend" and decided.needs_escalation is False
    unmatched = router.score("compose a symphony in D minor", ROSTER)
    assert unmatched.decided is None and unmatched.needs_escalation is True


def test_threshold_turns_a_weak_match_into_an_abstain():
    weak = "react to the database change"           # one term for each lane
    assert DecisionRouter(threshold=0.0).score(weak, ROSTER).decided is not None
    assert DecisionRouter(threshold=0.99).score(weak, ROSTER).decided is None


def test_candidate_scores_are_probabilities_summing_to_one():
    r = DecisionRouter().score("css layout for the react page", ROSTER)
    assert abs(sum(c.score for c in r.candidates) - 1.0) < 1e-5
    assert r.candidates[0].agent == "frontend"
    assert r.confidence == r.candidates[0].score


def test_probabilities_uniform_on_no_signal_and_peaked_on_signal():
    assert probabilities([0.0, 0.0], 1.0) == [0.5, 0.5]
    peaked = probabilities([3.0, 0.0], 1.0)
    assert peaked[0] > 0.9


def test_terms_stem_plural_and_drop_stop_words():
    assert terms("The databases") == ["database"]
    assert terms("stories") == ["story"]
    assert terms("the") == []


def test_invalid_threshold_is_refused():
    with pytest.raises(ValueError):
        DecisionRouter(threshold=1.5)


def test_calibration_reaches_the_requested_abstain_share():
    items = [{"text": t} for t in ("database schema api", "react css layout",
                                   "api for react", "symphony", "database",
                                   "css", "schema", "layout", "api", "react")]
    router = DecisionRouter()
    t10 = calibrate_threshold(router, items, ROSTER, abstain_share=0.10)
    t50 = calibrate_threshold(router, items, ROSTER, abstain_share=0.50)
    abst = lambda t: sum(DecisionRouter(threshold=t).score(i["text"], ROSTER).decided is None
                         for i in items)
    assert abst(t10) >= 1 and abst(t50) >= 5
    assert t50 >= t10


def test_abstain_stats_ratio_and_undefined_case():
    rows = [("a", "a", "a"), ("a", "a", "b"), ("a", None, "b"), ("b", None, "b")]
    s = abstain_stats(rows)
    assert s["decided_error_rate"] == 0.5 and s["abstained_error_rate"] == 0.5
    assert s["error_ratio"] == 1.0
    clean = abstain_stats([("a", "a", "a"), ("a", None, "b")])
    assert clean["error_ratio"] is None


def test_split_is_deterministic_and_covers_every_item():
    items = [{"id": f"r{i:03d}"} for i in range(40)]
    dev, test = split(items)
    assert (dev, test) == split(items)
    assert sorted(x["id"] for x in dev + test) == sorted(x["id"] for x in items)
    assert split(items, seed=1) != (dev, test)


def test_bench_reproduces_the_reported_result():
    items = json.loads(FIXTURE.read_text(encoding="utf-8"))["items"]
    out = run(items, load_default())
    assert out["bar"] == {"A1_accuracy": True, "A2_abstain_under_15pct": False,
                          "A3_error_ratio_at_least_2": True, "control_fails_A3": True}
    assert out["decision"]["top1_accuracy"] > out["lexical"]["top1_accuracy"]
    assert out == run(items, load_default())
