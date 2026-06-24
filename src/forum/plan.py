from __future__ import annotations

from dataclasses import dataclass


class CycleError(Exception):
    """Raised when the task DAG contains a dependency cycle."""


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    agent: str
    instruction: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Plan:
    tasks: tuple[Task, ...]

    def schedule(self) -> list[list[str]]:
        """Kahn layering -> ordered list of parallel waves (sorted ids per wave)."""
        ids = {t.id for t in self.tasks}
        remaining = {t.id: set(t.depends_on) for t in self.tasks}
        for tid, deps in remaining.items():
            unknown = deps - ids
            if unknown:
                raise ValueError(f"task {tid!r} depends on unknown task(s): {sorted(unknown)}")

        waves: list[list[str]] = []
        done: set[str] = set()
        while remaining:
            ready = sorted(tid for tid, deps in remaining.items() if deps <= done)
            if not ready:
                raise CycleError(f"dependency cycle among: {sorted(remaining)}")
            waves.append(ready)
            done.update(ready)
            for tid in ready:
                del remaining[tid]
        return waves
