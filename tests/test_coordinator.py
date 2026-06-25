import asyncio

import pytest

from forum.control import Coordinator
from forum.executor import Result
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

[[agent]]
name="docs"
category="support"
domain="docs"
keywords=["docs"]
model_tier="cheap"
executor="echo"
"""
)

PLAN_JSON = """{"tasks": [
  {"id": "T1", "agent": "backend", "instruction": "build the api", "depends_on": []},
  {"id": "T2", "agent": "docs", "instruction": "document it", "depends_on": ["T1"]}
]}"""


class _Canned:
    def __init__(self, output):
        self._output = output

    async def run(self, assignment):
        return Result(assignment.task_id, assignment.agent, self._output)


def test_coordinator_builds_a_plan():
    plan = asyncio.run(Coordinator().plan("ship an api with docs", ROSTER, _Canned(PLAN_JSON)))
    assert [t.id for t in plan.tasks] == ["T1", "T2"]
    assert plan.schedule() == [["T1"], ["T2"]]


def test_coordinator_rejects_unknown_agent():
    bad = '{"tasks": [{"id": "T1", "agent": "ghost", "instruction": "x", "depends_on": []}]}'
    with pytest.raises(ValueError, match="ghost"):
        asyncio.run(Coordinator().plan("x", ROSTER, _Canned(bad)))


def test_coordinator_handles_braces_in_request():
    plan = asyncio.run(Coordinator().plan("build a config with {host} and {port}", ROSTER, _Canned(PLAN_JSON)))
    assert [t.id for t in plan.tasks] == ["T1", "T2"]


_TYPED_PLAN_JSON = """{"tasks": [
  {"id": "T1", "agent": "backend", "instruction": "build the api", "depends_on": []},
  {"id": "T2", "agent": "docs", "instruction": "document it", "depends_on": [{"id": "T1", "type": "order"}]}
]}"""


def test_coordinator_parses_typed_edges():
    plan = asyncio.run(Coordinator().plan("ship an api with docs", ROSTER, _Canned(_TYPED_PLAN_JSON)))
    t2 = plan.tasks[1]
    assert t2.depends_on == ("T1",)          # still a scheduling dependency
    assert t2.order_deps == frozenset({"T1"})  # but ordering-only, no data flow
    assert t2.data_deps == ()


def test_coordinator_plain_string_dep_is_a_data_edge():
    plan = asyncio.run(Coordinator().plan("ship an api with docs", ROSTER, _Canned(PLAN_JSON)))
    t2 = plan.tasks[1]
    assert t2.depends_on == ("T1",)
    assert t2.order_deps == frozenset()      # a plain id defaults to a data edge
    assert t2.data_deps == ("T1",)


def test_coordinator_rejects_dep_object_without_id():
    bad = '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "x", "depends_on": [{"type": "order"}]}]}'
    with pytest.raises(ValueError, match="missing 'id'"):
        asyncio.run(Coordinator().plan("x", ROSTER, _Canned(bad)))
