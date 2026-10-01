from __future__ import annotations

from forum.executor import Assignment, Executor, Result, executor_id
from forum.roster import Roster


class TieredExecutor:
    """Route task assignments to executors by the agent's roster model tier."""

    model_id = "tiered"

    def __init__(
        self,
        roster: Roster,
        default: Executor,
        *,
        tiers: dict[str, Executor] | None = None,
    ) -> None:
        self._roster = roster
        self._default = default
        self._tiers = dict(tiers or {})

    def select(self, assignment: Assignment) -> Executor:
        spec = self._roster.by_name(assignment.agent)
        if spec is None:
            return self._default
        return self._tiers.get(spec.model_tier, self._default)

    def model_id_for(self, assignment: Assignment) -> str:
        return executor_id(self.select(assignment))

    async def run(self, assignment: Assignment) -> Result:
        return await self.select(assignment).run(assignment)
