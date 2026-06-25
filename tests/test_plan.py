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


def test_data_deps_excludes_order_only():
    t = Task("T3", "x", "go", ("T1", "T2"), frozenset({"T2"}))
    assert t.data_deps == ("T1",)              # T2 is order-only, so it carries no data
    assert set(t.depends_on) == {"T1", "T2"}   # both still constrain scheduling


def test_order_edge_still_constrains_scheduling():
    plan = Plan(
        (
            Task("T1", "x", "a", ()),
            Task("T2", "x", "b", ("T1",), frozenset({"T1"})),  # order-only dep
        )
    )
    assert plan.schedule() == [["T1"], ["T2"]]  # an order edge sequences like any dep
