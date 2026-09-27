from __future__ import annotations

import asyncio
import ntpath
import os
import subprocess
from dataclasses import dataclass
from typing import Protocol

from forum._vendor import safe_spawn
from forum.spawn_guard import check_command_name, guarded_environ

# Agent CLIs get an isolation profile. A profile safe_spawn has proven (claude,
# codex, from the Q0 PROBES.md) is applied; an unproven one (gemini, opencode) is
# refused unless a launch grant names it. A plain model command (ollama, a python
# adapter, a local server CLI) is not an agent CLI and takes no profile, but still
# runs isolated: an absolute executable, a private empty folder, an environment
# allowlist, and cmd.exe metacharacters refused for a .cmd or .bat target.
_AGENT_CLIS = ("claude", "codex", "gemini", "opencode")
# Agent CLIs whose proven profile reads the task on stdin, and the arguments that
# ask for it. npm installs these as .cmd shims on Windows, and a batch target
# refuses a line break in any argument, so the task never rides on argv: a task
# with upstream results or done criteria would otherwise always be refused.
_STDIN_TASK_ARGS = {"claude": (), "codex": ("-",)}
# The codex profile starts with the `exec` subcommand; a command that already
# names it (or its alias `e`) would pass it twice.
_PROFILE_SUBCOMMANDS = {"codex": ("exec", "e")}


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
    ``SubprocessExecutor(["python", "-c", "..."])`` works. An agent CLI with a
    proven profile (claude, codex) reads the task on stdin instead, so
    ``SubprocessExecutor(["claude", "-p"])`` runs any task through npm's batch
    shim. The child starts through the vendored ``safe_spawn``: the executable is
    resolved to an absolute path (a bare name is looked up on PATH only, never the
    working folder, and a PATH entry inside the working folder is skipped), the child
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

    def _args_and_input(self, instruction: str) -> tuple[list[str], str | None]:
        """The caller's arguments plus the task, and the task text for stdin (or None)."""
        caller = self._command[1:]
        profile = self._profile if isinstance(self._profile, str) else None
        if profile is not None and caller[:1] and caller[0] in _PROFILE_SUBCOMMANDS.get(profile, ()):
            caller = caller[1:]
        if profile in _STDIN_TASK_ARGS:
            return [*caller, *_STDIN_TASK_ARGS[profile]], instruction
        return [*caller, instruction], None

    async def run(self, assignment: Assignment) -> Result:
        args, task_input = self._args_and_input(assignment.instruction)
        try:
            check_command_name(self._command[0])
            proc = await asyncio.to_thread(
                safe_spawn.run,
                self._command[0],
                args,
                profile=self._profile,
                override_var=self._override_var,
                input=task_input,
                timeout=self._timeout,
                allow_env=self._allow_env,
                grants=self._grants,
                environ=guarded_environ(),
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


def _names(variable: str) -> tuple[str, ...]:
    raw = os.environ.get(variable, "")
    return tuple(name.strip() for name in raw.replace(",", " ").split() if name.strip())


def launch_grants() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(allow_env, grants) from FORUM_CHILD_ENV and FORUM_ALLOW_EXEC_CLI.

    Launch-only: read from the environment the person started forum with, never
    from a tool argument, so a model that controls arguments cannot widen a
    child's environment or enable an unproven agent CLI. Grants are lowercased to
    match safe_spawn profile names.
    """
    return _names("FORUM_CHILD_ENV"), tuple(n.lower() for n in _names("FORUM_ALLOW_EXEC_CLI"))


def command_executor(command: list[str]) -> SubprocessExecutor:
    """A SubprocessExecutor for a launch-configured command, with the launch grants.

    Every command the person configures (--cmd, a tier flag, a --runtime-config
    entry) goes through here, so each one honors the same launch variables.
    """
    allow_env, grants = launch_grants()
    return SubprocessExecutor(command, allow_env=allow_env, grants=grants)


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
