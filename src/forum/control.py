from __future__ import annotations

from dataclasses import dataclass

from forum.executor import Assignment, Executor
from forum.llm import ask_json
from forum.plan import Plan, Task
from forum.roster import Roster

_COORDINATOR_PROMPT = """You are a planner. Break the request into a minimal task DAG.
Available agents: {agents}.
Return ONLY JSON of the form:
{{"tasks": [{{"id": "T1", "agent": "<one of the agents>", "instruction": "...", "depends_on": []}}]}}
Use depends_on to order tasks. Keep the plan small.

Request: {request}"""


class Coordinator:
    """Turn a plain request into a validated task plan, using a model."""

    async def plan(self, request: str, roster: Roster, executor: Executor) -> Plan:
        names = [a.name for a in roster.agents]
        prompt = _COORDINATOR_PROMPT.format(request=request, agents=", ".join(names))
        data = await ask_json(executor, "coordinator", prompt)
        tasks = tuple(
            Task(
                str(t["id"]),
                str(t["agent"]),
                str(t["instruction"]),
                tuple(str(d) for d in t.get("depends_on", [])),
            )
            for t in data["tasks"]
        )
        for t in tasks:
            if t.agent not in names:
                raise ValueError(f"coordinator chose unknown agent: {t.agent!r}")
        plan = Plan(tasks)
        plan.schedule()  # raises on a cycle or an unknown dependency
        return plan
