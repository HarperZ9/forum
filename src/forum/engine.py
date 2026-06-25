from __future__ import annotations

from forum.control import Classifier, Coordinator, Synthesizer, Validator
from forum.dispatch import dispatch_plan
from forum.executor import Executor, Result
from forum.ledger import Ledger
from forum.plan import Plan
from forum.policy import Policy
from forum.roster import Roster
from forum.routing import LexicalRouter, RouteResult, RoutingProvider


class Orchestrator:
    """Ties routing + planning + witnessed dispatch into one entry point."""

    def __init__(
        self,
        roster: Roster,
        ledger: Ledger,
        executor: Executor,
        policy: Policy,
        router: RoutingProvider | None = None,
        coordinator: Coordinator | None = None,
        classifier: Classifier | None = None,
        validator: Validator | None = None,
        synthesizer: Synthesizer | None = None,
    ) -> None:
        self.roster = roster
        self.ledger = ledger
        self.executor = executor
        self.policy = policy
        self.router = router or LexicalRouter()
        self.coordinator = coordinator or Coordinator()
        # available for Tier-2 routing escalation; submit() uses the Coordinator's direct assignment
        self.classifier = classifier or Classifier()
        self.validator = validator or Validator()
        self.synthesizer = synthesizer or Synthesizer()

    def route(self, text: str) -> RouteResult:
        return self.router.score(text, self.roster)

    async def submit_plan(self, plan: Plan) -> dict[str, Result]:
        """Witness the request and run the plan through the witnessed dispatcher.

        Note: plan-level agent/category authorization (policy.permits) is a later
        concern; today only policy.max_parallel is applied, at dispatch.
        """
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

    async def submit(self, request: str) -> str:
        """Plan a plain request, run it, validate each result, and answer.

        Every step (request, plan, tasks, results, verdicts, the answer) is
        appended to the ledger, so the whole run is verifiable afterward.
        """
        req = self.ledger.append(actor="client", kind="request", payload={"text": request})
        plan = await self.coordinator.plan(request, self.roster, self.executor)
        results = await dispatch_plan(
            plan, self.ledger, self.executor,
            max_parallel=self.policy.max_parallel, parent_seq=req.seq,
        )
        for task in plan.tasks:
            result = results.get(task.id)
            if result is None:
                continue
            # Link the verdict to the specific result entry it judges, so
            # causal_chain(verdict) reconstructs request -> plan -> task -> result -> verdict.
            parent = result.witnessed_seq if result.witnessed_seq is not None else req.seq
            if not result.ok:
                # the task itself failed; witness the failure rather than ask the judge to bless it
                self.ledger.append(
                    actor="validator",
                    kind="verdict",
                    payload={"id": task.id, "ok": False, "score": 0.0, "reason": "task failed"},
                    causal_parent=parent,
                )
                continue
            verdict = await self.validator.validate(task.instruction, result.output, self.executor)
            self.ledger.append(
                actor="validator",
                kind="verdict",
                payload={"id": task.id, "ok": verdict.ok, "score": verdict.score, "reason": verdict.reason},
                causal_parent=parent,
            )
        answer = await self.synthesizer.synthesize(request, results, self.executor)
        self.ledger.append(actor="synthesizer", kind="result", payload={"answer": answer}, causal_parent=req.seq)
        return answer
