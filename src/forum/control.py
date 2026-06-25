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


@dataclass(frozen=True, slots=True)
class Classification:
    agent: str
    confidence: float
    reason: str


_CLASSIFIER_PROMPT = """Pick the single best agent for the task.
Agents: {agents}.
Return ONLY JSON of the form:
{{"agent": "<one of the agents>", "confidence": 0.0, "reason": "..."}}

Task: {task}"""


class Classifier:
    """Pick an agent for a single task when keyword routing cannot decide."""

    async def classify(self, task: str, roster: Roster, executor: Executor) -> Classification:
        names = [a.name for a in roster.agents]
        prompt = _CLASSIFIER_PROMPT.format(task=task, agents=", ".join(names))
        data = await ask_json(executor, "classifier", prompt)
        agent = str(data["agent"])
        if agent not in names:
            raise ValueError(f"classifier chose unknown agent: {agent!r}")
        return Classification(agent, float(data.get("confidence", 0.0)), str(data.get("reason", "")))


@dataclass(frozen=True, slots=True)
class Verdict:
    ok: bool
    score: float
    reason: str


_VALIDATOR_PROMPT = """Judge whether the output satisfies the instruction.
Return ONLY JSON of the form:
{{"ok": true, "score": 0.0, "reason": "..."}}

Instruction: {instruction}
Output: {output}"""


class Validator:
    """Judge an output against its instruction, using a model."""

    async def validate(self, instruction: str, output: str, executor: Executor) -> Verdict:
        prompt = _VALIDATOR_PROMPT.format(instruction=instruction, output=output)
        data = await ask_json(executor, "validator", prompt)
        return Verdict(bool(data["ok"]), float(data.get("score", 0.0)), str(data.get("reason", "")))


_SYNTHESIZER_PROMPT = """Combine the task results into one clear answer to the request.

Request: {request}
Results:
{results}

Write the final answer."""


class Synthesizer:
    """Combine task results into one answer, using a model."""

    async def synthesize(self, request: str, results: dict, executor: Executor) -> str:
        lines = "\n".join(f"- {tid}: {r.output}" for tid, r in results.items())
        prompt = _SYNTHESIZER_PROMPT.format(request=request, results=lines)
        out = await executor.run(Assignment("control", "synthesizer", prompt))
        return out.output.strip()
