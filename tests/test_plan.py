import pytest

from forum.plan import CycleError, Plan, Task


def test_schedule_orders_into_waves():
    plan = Plan(
        (
            Task("T1", "backend", "schema", ()),
            Task("T2", "frontend", "ui", ("T1",)),
            Task("T3", "deep-research", "spec", ()),
            Task("T4", "code-review", "review", ("T2", "T3")),
        )
    )
    waves = plan.schedule()
    assert waves[0] == sorted(["T1", "T3"])
    assert waves[1] == ["T2"]
    assert waves[2] == ["T4"]


def test_cycle_is_detected():
    plan = Plan(
        (
            Task("A", "backend", "x", ("B",)),
            Task("B", "frontend", "y", ("A",)),
        )
    )
    with pytest.raises(CycleError):
        plan.schedule()


def test_unknown_dependency_rejected():
    plan = Plan((Task("A", "backend", "x", ("ghost",)),))
    with pytest.raises(ValueError, match="ghost"):
        plan.schedule()
