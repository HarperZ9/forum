from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Assignment:
    task_id: str
    agent: str
    instruction: str


@dataclass(frozen=True, slots=True)
class Result:
    task_id: str
    agent: str
    output: str
    ok: bool = True


class Executor(Protocol):
    async def run(self, assignment: Assignment) -> Result: ...


class EchoExecutor:
    """Deterministic stand-in executor: echoes the instruction as output.

    A real executor (Claude Code subagent / API / CLI) is a later milestone.
    """

    async def run(self, assignment: Assignment) -> Result:
        return Result(assignment.task_id, assignment.agent, f"done: {assignment.instruction}")
