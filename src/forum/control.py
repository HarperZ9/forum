from __future__ import annotations

from dataclasses import dataclass

from forum.executor import Assignment, Executor
from forum.llm import ask_json
from forum.plan import Plan, Task
from forum.roster import Roster

_COORDINATOR_PROMPT = """You are a planner. Break the request into a minimal task DAG.
Available agents: <<AGENTS>>.
Return ONLY JSON of the form:
{"tasks": [{"id": "T1", "agent": "<one of the agents>", "instruction": "...", "depends_on": []}]}
Use depends_on to order tasks. A dep may be a task id (the downstream task uses that
task's output) or {"id": "T1", "type": "order"} for run-after without using its output.
Keep the plan small.

Request: <<REQUEST>>"""


def _parse_deps(raw: object) -> tuple[tuple[str, ...], frozenset[str]]:
    """Parse a task's depends_on into (all dep ids, the order-only subset).

    Each entry is a task id string (a data edge) or {"id": "T1", "type": "order"}
    for an ordering-only edge. Unknown types default to a data edge. Raises a
    descriptive ValueError on malformed model output (not a list, or a dict dep
    missing its id), like the rest of this module.
    """
    if not isinstance(raw, list):
        raise ValueError(f"depends_on must be a list; got {type(raw).__name__}")
    deps: list[str] = []
    order: list[str] = []
    for d in raw:
        if isinstance(d, dict):
            if "id" not in d:
                raise ValueError(f"dependency object missing 'id': {d!r}")
            did = str(d["id"])
            if str(d.get("type", "data")) == "order":
                order.append(did)
        else:
            did = str(d)
        deps.append(did)
    return tuple(deps), frozenset(order)


class Coordinator:
    """Turn a plain request into a validated task plan, using a model."""

    async def plan(self, request: str, roster: Roster, executor: Executor, context: str = "") -> Plan:
        names = [a.name for a in roster.agents]
        prompt = _COORDINATOR_PROMPT.replace("<<AGENTS>>", ", ".join(names)).replace("<<REQUEST>>", request)
        if context:
            prompt = f"Context (organized knowledge to use):\n{context}\n\n" + prompt
        data = await ask_json(executor, "coordinator", prompt)
        if "tasks" not in data:
            raise ValueError(f"coordinator response missing 'tasks'; got keys {list(data)}")
        tasks = tuple(
            Task(str(t["id"]), str(t["agent"]), str(t["instruction"]), *_parse_deps(t.get("depends_on", [])))
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
Agents: <<AGENTS>>.
Return ONLY JSON of the form:
{"agent": "<one of the agents>", "confidence": 0.0, "reason": "..."}

Task: <<TASK>>"""


class Classifier:
    """Pick an agent for a single task when keyword routing cannot decide."""

    async def classify(self, task: str, roster: Roster, executor: Executor) -> Classification:
        names = [a.name for a in roster.agents]
        prompt = _CLASSIFIER_PROMPT.replace("<<AGENTS>>", ", ".join(names)).replace("<<TASK>>", task)
        data = await ask_json(executor, "classifier", prompt)
        if "agent" not in data:
            raise ValueError(f"classifier response missing 'agent'; got keys {list(data)}")
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
{"ok": true, "score": 0.0, "reason": "..."}

Instruction: <<INSTRUCTION>>
Output: <<OUTPUT>>"""


class Validator:
    """Judge an output against its instruction, using a model."""

    async def validate(self, instruction: str, output: str, executor: Executor) -> Verdict:
        prompt = _VALIDATOR_PROMPT.replace("<<INSTRUCTION>>", instruction).replace("<<OUTPUT>>", output)
        data = await ask_json(executor, "validator", prompt)
        if "ok" not in data:
            raise ValueError(f"validator response missing 'ok'; got keys {list(data)}")
        raw_ok = data["ok"]
        ok = raw_ok if isinstance(raw_ok, bool) else str(raw_ok).strip().lower() not in ("false", "0", "no", "")
        return Verdict(ok, float(data.get("score", 0.0)), str(data.get("reason", "")))


_INTENT_JUDGE_PROMPT = """Judge whether the answer actually addresses the request.
A lexical check flagged possible drift: these request terms do not appear in the answer: <<MISSING>>.
They may be absent because the answer paraphrased them (still fine) or because it ignored part of the request (real drift). Decide which.
Return ONLY JSON of the form:
{"ok": true, "score": 0.0, "reason": "..."}

Request: <<REQUEST>>
Answer: <<ANSWER>>"""


class IntentJudge:
    """Judge whether an answer addresses the request, using a model.

    The rung above the lexical coverage floor: when the floor flags a run, a model
    reads the request and the answer (told which request terms the floor found
    missing) and decides whether the answer truly drifted or merely paraphrased. Its
    verdict is witnessed with its reasoning, so it is auditable, not trusted.
    """

    async def judge(self, request: str, answer: str, missing: list[str], executor: Executor) -> Verdict:
        prompt = (
            _INTENT_JUDGE_PROMPT
            .replace("<<MISSING>>", ", ".join(missing) or "(none)")
            .replace("<<REQUEST>>", request)
            .replace("<<ANSWER>>", answer)
        )
        data = await ask_json(executor, "intent-judge", prompt)
        if "ok" not in data:
            raise ValueError(f"intent judge response missing 'ok'; got keys {list(data)}")
        raw_ok = data["ok"]
        ok = raw_ok if isinstance(raw_ok, bool) else str(raw_ok).strip().lower() not in ("false", "0", "no", "")
        return Verdict(ok, float(data.get("score", 0.0)), str(data.get("reason", "")))


_SYNTHESIZER_PROMPT = """Combine the task results into one clear answer to the request.

Request: <<REQUEST>>
Results:
<<RESULTS>>

<<DELIVERY_CONTRACT>>
Write the final answer."""


class Synthesizer:
    """Combine task results into one answer, using a model."""

    async def synthesize(
        self,
        request: str,
        results: dict,
        executor: Executor,
        delivery_contract: str = "",
    ) -> str:
        lines = "\n".join(f"- {tid}: {r.output}" for tid, r in results.items())
        contract = delivery_contract.strip()
        contract_block = f"Delivery contract:\n{contract}\n\n" if contract else ""
        prompt = (
            _SYNTHESIZER_PROMPT
            .replace("<<REQUEST>>", request)
            .replace("<<RESULTS>>", lines)
            .replace("<<DELIVERY_CONTRACT>>", contract_block)
        )
        out = await executor.run(Assignment("control:synthesizer", "synthesizer", prompt))
        return out.output.strip()
