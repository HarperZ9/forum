from __future__ import annotations

import asyncio
import ntpath
import subprocess
from dataclasses import dataclass
from typing import Protocol

from forum._vendor import safe_spawn

# Agent CLIs get an isolation profile. A profile safe_spawn has proven (claude,
# codex, from the Q0 PROBES.md) is applied; an unproven one (gemini, opencode) is
# refused unless a launch grant names it. A plain model command (ollama, a python
# adapter, a local server CLI) is not an agent CLI and takes no profile, but still
# runs isolated: an absolute executable, a private empty folder, an environment
# allowlist, and cmd.exe metacharacters refused for a .cmd or .bat target.
_AGENT_CLIS = ("claude", "codex", "gemini", "opencode")


def _agent_profile(target: str) -> str | None:
    """The isolation profile name for a target that is a known agent CLI, else None."""
    base = ntpath.splitext(ntpath.basename(str(target)))[0].lower()  # splits on / and \
    return base if base in _AGENT_CLIS else None


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
    """Run an external command per task and capture its output, isolated.

    The task instruction is appended to ``command`` as a final argument, so
    ``SubprocessExecutor(["python", "-c", "..."])`` or a model CLI such as
    ``SubprocessExecutor(["claude", "-p"])`` both work. The child starts through
    the vendored ``safe_spawn``: the executable is resolved to an absolute path
    (a bare name is looked up on PATH only, never the working folder), the child
    runs in a new private empty folder, its environment is an allowlist (the
    platform base plus ``allow_env`` and the profile's variables, never the whole
    environment), a ``.cmd`` or ``.bat`` target refuses an instruction holding
    cmd.exe metacharacters, and a Python target gets ``-P``. A known agent CLI
    (claude, codex, gemini, opencode) gets its isolation ``profile``; an unproven
    profile is refused unless ``grants`` names it. Process IO lives here, at the
    edge; the core stays pure.
    """

    def __init__(
        self,
        command: list[str],
        *,
        timeout: float = 60.0,
        profile: str | None = None,
        override_var: str | None = None,
        allow_env: tuple[str, ...] = (),
        grants: tuple[str, ...] = (),
    ) -> None:
        self._command = list(command)
        self._timeout = timeout
        # An explicit profile wins; otherwise detect a known agent CLI by name.
        self._profile = profile if profile is not None else _agent_profile(self._command[0])
        self._override_var = override_var
        self._allow_env = tuple(allow_env)
        self._grants = tuple(grants)

    async def run(self, assignment: Assignment) -> Result:
        args = [*self._command[1:], assignment.instruction]
        try:
            proc = await asyncio.to_thread(
                safe_spawn.run,
                self._command[0],
                args,
                profile=self._profile,
                override_var=self._override_var,
                timeout=self._timeout,
                allow_env=self._allow_env,
                grants=self._grants,
            )
        except safe_spawn.SpawnRefused as exc:
            # A refusal is a witnessed failure, not a crash: the child never
            # started. exc.code is a stable slug; the message names no resolved
            # path, argument or value.
            return Result(assignment.task_id, assignment.agent, f"error: {exc.code}: {exc}", ok=False)
        except subprocess.TimeoutExpired:
            return Result(assignment.task_id, assignment.agent, "error: timeout", ok=False)
        ok = proc.returncode == 0
        text = (proc.stdout if ok else (proc.stderr or proc.stdout) or "").strip()
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
