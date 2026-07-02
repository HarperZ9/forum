from __future__ import annotations

import asyncio
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
    witnessed_seq: int | None = None  # ledger seq of this result's entry, set by the dispatcher


class Executor(Protocol):
    async def run(self, assignment: Assignment) -> Result: ...


class EchoExecutor:
    """Deterministic stand-in executor: echoes the instruction as output.

    A real executor (Claude Code subagent / API / CLI) is a later milestone.
    """

    async def run(self, assignment: Assignment) -> Result:
        return Result(assignment.task_id, assignment.agent, f"done: {assignment.instruction}")


class SubprocessExecutor:
    """Run an external command per task and capture its output.

    The task instruction is appended to ``command`` as a final argument, so
    ``SubprocessExecutor(["python", "-c", "..."])`` or a model CLI such as
    ``SubprocessExecutor(["claude", "-p"])`` both work. Process IO lives here, at
    the edge; the core stays pure.
    """

    def __init__(self, command: list[str], *, timeout: float = 60.0) -> None:
        self._command = list(command)
        self._timeout = timeout

    async def run(self, assignment: Assignment) -> Result:
        proc = await asyncio.create_subprocess_exec(
            *self._command,
            assignment.instruction,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), self._timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return Result(assignment.task_id, assignment.agent, "error: timeout", ok=False)
        ok = proc.returncode == 0
        text = (out if ok else (err or out)).decode("utf-8", "replace").strip()
        return Result(assignment.task_id, assignment.agent, text, ok=ok)


def executor_id(executor) -> str:
    """A short identity for an executor: its model_id if it exposes one, else its type name.

    Recorded on result entries so the ledger shows which model produced each output
    (reproducibility, and detecting silent provider/model drift).
    """
    return getattr(executor, "model_id", None) or type(executor).__name__


def assignment_model_id(executor, assignment: Assignment) -> str:
    """Executor identity for one assignment, when a wrapper can route per task."""
    model_id_for = getattr(executor, "model_id_for", None)
    if callable(model_id_for):
        return model_id_for(assignment)
    return executor_id(executor)
