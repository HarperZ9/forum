from __future__ import annotations

from forum.dispatch import dispatch_plan
from forum.executor import Executor, Result
from forum.ledger import Ledger
from forum.plan import Plan
from forum.policy import Policy
from forum.roster import Roster
from forum.routing import LexicalRouter, RouteResult


class Orchestrator:
    """Ties routing + planning + witnessed dispatch into one entry point."""

    def __init__(
        self,
        roster: Roster,
        ledger: Ledger,
        executor: Executor,
        policy: Policy,
        router: LexicalRouter | None = None,
    ) -> None:
        self.roster = roster
        self.ledger = ledger
        self.executor = executor
        self.policy = policy
        self.router = router or LexicalRouter()

    def route(self, text: str) -> RouteResult:
        return self.router.score(text, self.roster)

    async def submit_plan(self, plan: Plan) -> dict[str, Result]:
        request = self.ledger.append(
            actor="client", kind="request", payload={"tasks": [t.id for t in plan.tasks]}
        )
        return await dispatch_plan(
            plan,
            self.ledger,
            self.executor,
            max_parallel=self.policy.max_parallel,
            parent_seq=request.seq,
        )
