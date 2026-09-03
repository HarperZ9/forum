import pytest

from forum.context_budget import (
    ContextBudget,
    ContextBudgetMeter,
    apply_context_budget,
    approx_tokens,
    observed_context_budget,
    pressure_payload,
)


def test_approx_tokens_uses_utf8_bytes_and_ceil():
    assert approx_tokens("") == 0
    assert approx_tokens("abcd") == 1
    assert approx_tokens("abcde") == 2
    assert approx_tokens("\u5b57") == 1
    assert approx_tokens("\u5b57\u5b57") == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_total_tokens": -1},
        {"max_request_tokens": -1},
        {"max_task_tokens": -1},
        {"max_upstream_tokens": -1},
        {"bytes_per_token": 0},
    ],
)
def test_context_budget_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):
        ContextBudget(**kwargs)


def test_context_under_budget_is_retained():
    budget = ContextBudget(max_task_tokens=10)
    meter = ContextBudgetMeter()
    admitted, pressure = apply_context_budget("task", "T1", "small context", budget, meter)
    assert admitted == "small context"
    assert pressure.action == "retained"
    assert pressure.reason == "under_budget"
    assert meter.admitted_tokens_total == pressure.admitted_tokens


def test_context_over_source_limit_is_trimmed():
    budget = ContextBudget(max_task_tokens=2)
    meter = ContextBudgetMeter()
    admitted, pressure = apply_context_budget("task", "T1", "abcdefghijklmnop", budget, meter)
    assert admitted == "abcdefgh"
    assert pressure.action == "trimmed"
    assert pressure.reason == "max_task_tokens"
    assert pressure.original_tokens == 4
    assert pressure.admitted_tokens == 2


def test_total_budget_can_omit_later_context():
    budget = ContextBudget(max_total_tokens=2)
    meter = ContextBudgetMeter()
    first, first_pressure = apply_context_budget("request", "request", "abcdefgh", budget, meter)
    second, second_pressure = apply_context_budget("task", "T1", "abcd", budget, meter)
    assert first == "abcdefgh"
    assert first_pressure.action == "retained"
    assert second == ""
    assert second_pressure.action == "omitted"
    assert second_pressure.reason == "max_total_tokens"


def test_pressure_payload_and_observed_summary():
    budget = ContextBudget(max_total_tokens=2)
    meter = ContextBudgetMeter()
    apply_context_budget("request", "request", "abcdefgh", budget, meter)
    _, pressure = apply_context_budget("task", "T1", "abcd", budget, meter)
    payload = pressure_payload(pressure, budget, meter)
    assert payload["schema"] == "forum.context-pressure/v1"
    assert payload["remaining_total_tokens"] == 0
    observed = observed_context_budget(meter.pressures)
    assert observed == {
        "checks": 2,
        "trimmed": 0,
        "omitted": 1,
        "tokens_original": 3,
        "tokens_admitted": 2,
        "tokens_saved": 1,
    }


def test_the_total_is_named_when_both_caps_bind_equally():
    """Both caps allow the same number of tokens here. The reason names one of
    them, and naming the total is what tells a reader the run is nearly out
    rather than that this one source is large."""
    budget = ContextBudget(max_total_tokens=5, max_task_tokens=5)
    meter = ContextBudgetMeter()
    _, pressure = apply_context_budget("task", "T1", "x" * 100, budget, meter)
    assert pressure.action == "trimmed"
    assert pressure.reason == "max_total_tokens"
    assert pressure.admitted_tokens == 5


def test_a_character_split_by_the_trim_is_dropped_not_mangled():
    """The cut is measured in bytes, so it can land inside a character. The
    slice decodes with errors ignored, which drops the half character instead
    of admitting a broken one."""
    two_byte = chr(0x00E9)  # e-acute, two bytes in UTF-8
    budget = ContextBudget(max_request_tokens=1, bytes_per_token=3)
    meter = ContextBudgetMeter()
    admitted, pressure = apply_context_budget("request", "request", two_byte * 10, budget, meter)
    assert admitted == two_byte
    assert pressure.admitted_bytes == 2
    assert pressure.action == "trimmed"


def test_empty_context_is_still_recorded_as_a_check():
    """Nothing to admit and nothing to trim, but the tally counts checks, so
    dropping the record would make a run look like it examined less than it
    did."""
    budget = ContextBudget(max_total_tokens=0)
    meter = ContextBudgetMeter()
    admitted, pressure = apply_context_budget("request", "request", "", budget, meter)
    assert admitted == ""
    assert pressure.action == "retained"
    assert pressure.reason == "empty"
    assert observed_context_budget(meter.pressures)["checks"] == 1
