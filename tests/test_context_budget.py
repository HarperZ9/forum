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
