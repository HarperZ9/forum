from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable

from forum.budget import RunBudget
from forum.context import ContextProvider, NullContextProvider
from forum.control import Classifier, Coordinator, IntentJudge, Synthesizer, Validator
from forum.dispatch import dispatch_plan
from forum.executor import Assignment, Executor, Result, executor_id
from forum.intent import DEFAULT_THRESHOLD, coverage
from forum.ledger import Ledger
from forum.plan import Plan, Task
from forum.policy import Policy
from forum.roster import Roster
from forum.routing import LexicalRouter, RouteResult, RoutingProvider


class _Meter:
    """A shared tally of executor calls across a run, for the budget."""

    def __init__(self) -> None:
        self.calls = 0


class _Counted:
    """Wraps an executor so each run() increments a shared meter; passes model_id through."""

    def __init__(self, inner: Executor, meter: _Meter) -> None:
        self._inner = inner
        self._meter = meter

    @property
    def model_id(self) -> str:
        return executor_id(self._inner)

    async def run(self, assignment: Assignment) -> Result:
        self._meter.calls += 1
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
        escalation_executors: list[Executor] | None = None,
        intent_threshold: float = DEFAULT_THRESHOLD,
        intent_judge: IntentJudge | None = None,
    ) -> None:
        self.roster = roster
        self.ledger = ledger
        self.executor = executor
        self.policy = policy
        self.intent_threshold = intent_threshold
        # opt-in: when set, a flagged run escalates from the lexical floor to a model judge
        self.intent_judge = intent_judge
        self.context_provider = context_provider or NullContextProvider()
        # ordered ladder of stronger executors; a failed task escalates up it (witnessed)
        self.escalation_executors = list(escalation_executors or [])
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
        meter = _Meter()
        counter = _Counted(self.executor, meter)
        ladder = [_Counted(e, meter) for e in self.escalation_executors]
        start = time.monotonic()

        def over_budget() -> bool:
            if budget is None:
                return False
            if budget.max_model_calls is not None and meter.calls >= budget.max_model_calls:
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
        failed: list[Task] = []
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
                failed.append(task)
            elif not await self._witness_verdict(task.id, task.instruction, result, vparent, counter):
                failed.append(task)

        # Escalation: a failed task is retried up the ladder of stronger executors,
        # triggered by the witnessed verdict (auditable), not opaque model confidence.
        for task in failed:
            for stronger in ladder:
                if over_budget():
                    break
                current = results.get(task.id)
                cur_seq = current.witnessed_seq if current and current.witnessed_seq is not None else req.seq
                esc = self.ledger.append(
                    actor="orchestrator", kind="tier_escalation",
                    payload={"id": task.id, "to": stronger.model_id, "reason": "validation failed"},
                    causal_parent=cur_seq,
                )
                try:
                    retry = await stronger.run(Assignment(task.id, task.agent, task.instruction))
                except Exception as exc:
                    retry = Result(task.id, task.agent, f"error: {exc}", ok=False)
                entry = self.ledger.append(
                    actor=task.agent, kind="result",
                    payload={"id": task.id, "output": retry.output, "ok": retry.ok, "model": stronger.model_id},
                    causal_parent=esc.seq,
                )
                retry = dataclasses.replace(retry, witnessed_seq=entry.seq)
                results[task.id] = retry
                if await self._witness_verdict(task.id, task.instruction, retry, entry.seq, counter):
                    break

        if over_budget():
            self.ledger.append(
                actor="budget", kind="budget",
                payload={"model_calls": meter.calls, "reason": "run stopped on budget"},
                causal_parent=req.seq,
            )
            answer = "Run stopped: budget exceeded before completion."
            self.ledger.append(actor="synthesizer", kind="result", payload={"answer": answer}, causal_parent=req.seq)
            return answer

        answer = await self.synthesizer.synthesize(request, results, counter)
        answer_entry = self.ledger.append(
            actor="synthesizer", kind="result", payload={"answer": answer}, causal_parent=req.seq
        )
        await self._witness_intent(request, answer, answer_entry.seq, counter, over_budget)
        return answer

    async def _witness_verdict(
        self, task_id: str, instruction: str, result: Result, parent_seq: int, executor: Executor
    ) -> bool:
        """Witness a verdict for a result and return whether it passed."""
        if not result.ok:
            # the task itself failed; witness the failure rather than ask the judge to bless it
            self.ledger.append(
                actor="validator",
                kind="verdict",
                payload={"id": task_id, "ok": False, "score": 0.0, "reason": "task failed"},
                causal_parent=parent_seq,
            )
            return False
        # validate through the passed executor so the call counts against the run budget
        verdict = await self.validator.validate(instruction, result.output, executor)
        self.ledger.append(
            actor="validator",
            kind="verdict",
            payload={"id": task_id, "ok": verdict.ok, "score": verdict.score, "reason": verdict.reason},
            causal_parent=parent_seq,
        )
        return verdict.ok

    async def _witness_intent(
        self, request: str, answer: str, parent_seq: int, executor: Executor,
        over_budget: Callable[[], bool],
    ) -> None:
        """Witness whether the run answered the request, and escalate when it looks off.

        First a reproducible lexical coverage signal (forum.intent), recorded as its
        own entry chained to the answer, so a completed run carries an auditable hint
        of whether it drifted from what was asked. Each task can pass its own verdict
        while the run as a whole misses the request; this is the check at that level.
        The floor never blocks; it records the signal. Then, only when the floor flags
        drift and an intent judge is configured, a model resolves whether the answer
        truly drifted or merely paraphrased, witnessed and budget-bounded.
        """
        score, missing = coverage(request, answer)
        flagged = score < self.intent_threshold
        missing_sorted = sorted(missing)
        check = self.ledger.append(
            actor="intent",
            kind="intent_check",
            payload={
                # name the method in the record itself, so a ledger reader sees this is
                # a lexical-overlap signal, not a semantic judgment, without external docs
                "method": "lexical_coverage",
                "coverage": round(score, 4),
                "flagged": flagged,
                "missing": missing_sorted,
            },
            causal_parent=parent_seq,
        )
        # the rung above the floor: a model decides whether a flagged answer truly
        # drifted or just paraphrased. Chained to the flag it resolves, witnessed with
        # its reasoning, and skipped once the budget is spent.
        if flagged and self.intent_judge is not None and not over_budget():
            verdict = await self.intent_judge.judge(request, answer, missing_sorted, executor)
            self.ledger.append(
                actor="intent-judge",
                kind="intent_judgment",
                payload={"ok": verdict.ok, "score": verdict.score, "reason": verdict.reason},
                causal_parent=check.seq,
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
            payload={"id": "T1", "output": result.output, "ok": result.ok, "model": executor_id(self.executor)},
            causal_parent=assigned.seq,
        )
        await self._witness_verdict("T1", task, result, result_entry.seq, self.executor)
        return result
