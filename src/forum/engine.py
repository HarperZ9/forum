from __future__ import annotations

import time

from forum.budget import RunBudget
from forum.context import ContextProvider, NullContextProvider
from forum.control import Classifier, Coordinator, Synthesizer, Validator
from forum.dispatch import dispatch_plan
from forum.executor import Assignment, Executor, Result
from forum.ledger import Ledger
from forum.plan import Plan
from forum.policy import Policy
from forum.roster import Roster
from forum.routing import LexicalRouter, RouteResult, RoutingProvider


class _CountingExecutor:
    """Wraps an executor to count run() invocations against a run's budget."""

    def __init__(self, inner: Executor) -> None:
        self._inner = inner
        self.calls = 0

    async def run(self, assignment: Assignment) -> Result:
        self.calls += 1
        return await self._inner.run(assignment)


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
        context_provider: ContextProvider | None = None,
    ) -> None:
        self.roster = roster
        self.ledger = ledger
        self.executor = executor
        self.policy = policy
        self.context_provider = context_provider or NullContextProvider()
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

    async def submit(self, request: str, *, budget: RunBudget | None = None) -> str:
        """Plan a plain request, run it, validate each result, and answer.

        Pulls organized context from the ContextProvider first (witnessed), then
        plans, dispatches, validates, and synthesizes. A RunBudget bounds the run:
        when it is exceeded the run stops gracefully, witnesses a budget entry,
        and stays verifiable. Every step is appended to the ledger.
        """
        counter = _CountingExecutor(self.executor)
        start = time.monotonic()

        def over_budget() -> bool:
            if budget is None:
                return False
            if budget.max_model_calls is not None and counter.calls >= budget.max_model_calls:
                return True
            if budget.max_seconds is not None and (time.monotonic() - start) >= budget.max_seconds:
                return True
            return False

        req = self.ledger.append(actor="client", kind="request", payload={"text": request})
        context = self.context_provider.context(request)
        parent = req.seq
        if context:
            # Witness the exact context that shaped the plan, and chain
            # request -> context -> plan so the provenance is reconstructable.
            parent = self.ledger.append(
                actor="context", kind="context", payload={"context": context}, causal_parent=req.seq
            ).seq

        plan = await self.coordinator.plan(request, self.roster, counter, context=context)
        results = await dispatch_plan(
            plan, self.ledger, counter,
            max_parallel=self.policy.max_parallel, parent_seq=parent, over_budget=over_budget,
        )
        for task in plan.tasks:
            result = results.get(task.id)
            if result is None:
                continue
            # Link the verdict to the specific result entry it judges, so
            # causal_chain(verdict) reconstructs request -> plan -> task -> result -> verdict.
            vparent = result.witnessed_seq if result.witnessed_seq is not None else req.seq
            if result.ok and over_budget():
                # do not spend a model call validating once the budget is gone
                self.ledger.append(
                    actor="validator", kind="verdict",
                    payload={"id": task.id, "ok": False, "score": 0.0, "reason": "budget exceeded"},
                    causal_parent=vparent,
                )
            else:
                await self._witness_verdict(task.id, task.instruction, result, vparent)

        if over_budget():
            self.ledger.append(
                actor="budget", kind="budget",
                payload={"model_calls": counter.calls, "reason": "run stopped on budget"},
                causal_parent=req.seq,
            )
            answer = "Run stopped: budget exceeded before completion."
            self.ledger.append(actor="synthesizer", kind="result", payload={"answer": answer}, causal_parent=req.seq)
            return answer

        answer = await self.synthesizer.synthesize(request, results, counter)
        self.ledger.append(actor="synthesizer", kind="result", payload={"answer": answer}, causal_parent=req.seq)
        return answer

    async def _witness_verdict(self, task_id: str, instruction: str, result: Result, parent_seq: int) -> None:
        if not result.ok:
            # the task itself failed; witness the failure rather than ask the judge to bless it
            self.ledger.append(
                actor="validator",
                kind="verdict",
                payload={"id": task_id, "ok": False, "score": 0.0, "reason": "task failed"},
                causal_parent=parent_seq,
            )
            return
        verdict = await self.validator.validate(instruction, result.output, self.executor)
        self.ledger.append(
            actor="validator",
            kind="verdict",
            payload={"id": task_id, "ok": verdict.ok, "score": verdict.score, "reason": verdict.reason},
            causal_parent=parent_seq,
        )

    async def assign(self, task: str, *, parent_seq: int | None = None) -> str:
        """Resolve one task's agent through the routing ladder, witnessed.

        Tier-0 lexical routing decides when it can; otherwise it escalates to the
        Tier-2 Classifier. The route, and any classification, are both recorded.
        """
        routed = self.route(task)
        route_entry = self.ledger.append(
            actor="router",
            kind="route",
            payload={"task": task, "decided": routed.decided, "confidence": routed.confidence},
            causal_parent=parent_seq,
        )
        if routed.decided is not None:
            return routed.decided
        classification = await self.classifier.classify(task, self.roster, self.executor)
        self.ledger.append(
            actor="classifier",
            kind="classification",
            payload={
                "task": task,
                "agent": classification.agent,
                "confidence": classification.confidence,
                "reason": classification.reason,
            },
            causal_parent=route_entry.seq,
        )
        return classification.agent

    async def submit_one(self, task: str) -> Result:
        """Run a single task end to end through the routing ladder, witnessed.

        Picks the agent with assign() (router, then classifier on escalation),
        runs it, validates the result, and witnesses every step, so a one-off
        task is as accountable as a planned one.
        """
        req = self.ledger.append(actor="client", kind="request", payload={"text": task})
        agent = await self.assign(task, parent_seq=req.seq)
        # assign() witnessed the route (and any classification) as children of the
        # request; the task is parented to the request too, so the routing decision
        # and the work it produced are sibling consequences of the same request.
        assigned = self.ledger.append(
            actor="dispatch",
            kind="task",
            payload={"id": "T1", "agent": agent, "instruction": task},
            causal_parent=req.seq,
        )
        try:
            result = await self.executor.run(Assignment("T1", agent, task))
        except Exception as exc:
            result = Result("T1", agent, f"error: {exc}", ok=False)
        result_entry = self.ledger.append(
            actor=agent,
            kind="result",
            payload={"id": "T1", "output": result.output, "ok": result.ok},
            causal_parent=assigned.seq,
        )
        await self._witness_verdict("T1", task, result, result_entry.seq)
        return result
