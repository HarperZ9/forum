from __future__ import annotations

import dataclasses
import time
from collections.abc import Callable

from forum.budget import RunBudget
from forum.context import ContextProvider, NullContextProvider
from forum.context_budget import (
    ContextBudget,
    ContextBudgetMeter,
    apply_context_budget,
    pressure_payload,
)
from forum.control import Classifier, Coordinator, IntentJudge, Synthesizer, Validator
from forum.delivery import NullReviser, Reviser, assess
from forum.delivery_profile import assess_profile, get_profile, profile_payload
from forum.dispatch import augment_with_upstream, dispatch_plan
from forum.executor import (
    Assignment,
    Executor,
    Result,
    assignment_model_id,
    executor_id,
)
from forum.gates import GatePolicy
from forum.intent import DEFAULT_THRESHOLD, coverage
from forum.ledger import Ledger
from forum.plan import Plan, Task
from forum.policy import Policy
from forum.roster import Roster
from forum.routing import LexicalRouter, RouteResult, RoutingProvider
from forum.verify import NullVerifier, VerifierProvider


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

    def model_id_for(self, assignment: Assignment) -> str:
        return assignment_model_id(self._inner, assignment)

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
        verifier: VerifierProvider | None = None,
        reviser: Reviser | None = None,
    ) -> None:
        self.roster = roster
        self.ledger = ledger
        self.executor = executor
        self.policy = policy
        self.intent_threshold = intent_threshold
        # opt-in: when set, a flagged run escalates from the lexical floor to a model judge
        self.intent_judge = intent_judge
        # the peer of context: an external verifier checks the answer (default abstains)
        self.verifier = verifier or NullVerifier()
        # opt-in: tightens a flagged answer, then Forum verifies the revision before use
        self.reviser = reviser or NullReviser()
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

    async def submit_plan(
        self,
        plan: Plan,
        *,
        resume: bool = False,
        checkpoint_each_wave: bool = False,
        gates: GatePolicy | None = None,
    ) -> dict[str, Result]:
        """Witness the request and run the plan through the witnessed dispatcher.

        With ``resume=True`` a known plan picks up where a prior run left off,
        reusing tasks already witnessed as successful (the ledger is the resume
        state). With ``checkpoint_each_wave=True`` each wave boundary is witnessed
        and synced as a savepoint. With a ``gates`` GatePolicy a gated wave pauses
        for human approval at its boundary (gate_pending in the ledger); the
        operator resolves it and re-invokes with resume=True over the same ledger.
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
            resume=resume,
            checkpoint_each_wave=checkpoint_each_wave,
            gates=gates,
        )

    async def submit(
        self,
        request: str,
        *,
        budget: RunBudget | None = None,
        context_budget: ContextBudget | None = None,
        delivery_profile: str | None = None,
        checkpoint_each_wave: bool = False,
    ) -> str:
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
        context_meter = ContextBudgetMeter()
        selected_delivery_profile = get_profile(delivery_profile).name if delivery_profile is not None else None

        def over_budget() -> bool:
            if budget is None:
                return False
            if budget.max_model_calls is not None and meter.calls >= budget.max_model_calls:
                return True
            if budget.max_seconds is not None and (time.monotonic() - start) >= budget.max_seconds:
                return True
            return False

        req = self.ledger.append(actor="client", kind="request", payload={"text": request})
        from forum.route_frame import derive_route_frame, frame_payload

        route_frame = derive_route_frame(request, self.route(request), self.roster)
        self.ledger.append(
            actor="router",
            kind="route_frame",
            payload=frame_payload(route_frame),
            causal_parent=req.seq,
        )
        if selected_delivery_profile is None:
            selected_delivery_profile = get_profile(route_frame.delivery_profile).name
        context = self.context_provider.context(request)
        parent = req.seq
        if context_budget is not None:
            context, pressure = apply_context_budget(
                "request", "request", context, context_budget, context_meter
            )
            if pressure.original_tokens > 0:
                self.ledger.append(
                    actor="context-budget",
                    kind="context_budget",
                    payload=pressure_payload(pressure, context_budget, context_meter),
                    causal_parent=req.seq,
                )
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
            context_provider=self.context_provider,
            context_budget=context_budget,
            context_meter=context_meter,
            checkpoint_each_wave=checkpoint_each_wave,
        )
        failed: list[Task] = []
        for task in plan.tasks:
            result = results.get(task.id)
            if result is None:
                continue
            # Link the verdict to the specific result entry it judges, so
            # causal_chain(verdict) reconstructs request -> plan -> task -> result -> verdict
            # (with a per-task context entry between plan and task when a provider supplies one).
            vparent = result.witnessed_seq if result.witnessed_seq is not None else req.seq
            if result.ok and over_budget():
                # do not spend a model call validating once the budget is gone
                self.ledger.append(
                    actor="validator", kind="verdict",
                    payload={"id": task.id, "ok": False, "score": 0.0, "reason": "budget exceeded"},
                    causal_parent=vparent,
                )
                failed.append(task)
            elif not await self._witness_verdict(task.id, task.contract_instruction(), result, vparent, counter):
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
                # the stronger model gets the same upstream data context the first attempt had
                instruction, _ = augment_with_upstream(task, results)
                try:
                    retry = await stronger.run(Assignment(task.id, task.agent, instruction))
                except Exception as exc:
                    retry = Result(task.id, task.agent, f"error: {exc}", ok=False)
                entry = self.ledger.append(
                    actor=task.agent, kind="result",
                    payload={"id": task.id, "output": retry.output, "ok": retry.ok, "model": stronger.model_id},
                    causal_parent=esc.seq,
                )
                retry = dataclasses.replace(retry, witnessed_seq=entry.seq)
                results[task.id] = retry
                if await self._witness_verdict(task.id, task.contract_instruction(), retry, entry.seq, counter):
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

        synthesis_results = self._budget_synthesis_results(
            results, context_budget, context_meter, req.seq
        )
        answer = await self.synthesizer.synthesize(
            request,
            synthesis_results,
            counter,
            delivery_contract=self._delivery_contract(route_frame, selected_delivery_profile),
        )
        answer_entry = self.ledger.append(
            actor="synthesizer", kind="result", payload={"answer": answer}, causal_parent=req.seq
        )
        # delivery first, so intent and verification both see and chain to the delivered answer
        answer, answer_seq = self._resolve_delivery(request, answer, answer_entry.seq)
        self._witness_delivery_profile(answer, answer_seq, selected_delivery_profile)
        await self._witness_intent(request, answer, answer_seq, counter, over_budget)
        self._witness_verification(request, answer, answer_seq)
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

    def _budget_synthesis_results(
        self,
        results: dict[str, Result],
        context_budget: ContextBudget | None,
        context_meter: ContextBudgetMeter,
        fallback_parent_seq: int,
    ) -> dict[str, Result]:
        """Apply the run context budget to final synthesis inputs only.

        The witnessed task results remain full-fidelity in the ledger. This helper
        builds a prompt copy so the last model call is bounded by the same budget
        contract as inter-task upstream injection.
        """
        if context_budget is None:
            return results
        budgeted: dict[str, Result] = {}
        for task_id, result in results.items():
            output, pressure = apply_context_budget(
                "upstream",
                f"{task_id}->synthesizer",
                result.output,
                context_budget,
                context_meter,
            )
            if pressure.original_tokens > 0:
                self.ledger.append(
                    actor="context-budget",
                    kind="context_budget",
                    payload=pressure_payload(pressure, context_budget, context_meter),
                    causal_parent=(
                        result.witnessed_seq
                        if result.witnessed_seq is not None
                        else fallback_parent_seq
                    ),
                )
            budgeted[task_id] = dataclasses.replace(result, output=output)
        return budgeted

    def _witness_delivery_profile(
        self,
        answer: str,
        parent_seq: int,
        profile: str | None,
    ) -> None:
        if profile is None:
            return
        assessment = assess_profile(answer, profile)
        self.ledger.append(
            actor="delivery-profile",
            kind="delivery_profile_check",
            payload=profile_payload(assessment),
            causal_parent=parent_seq,
        )

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
            try:
                verdict = await self.intent_judge.judge(request, answer, missing_sorted, executor)
                payload = {"ok": verdict.ok, "score": verdict.score, "reason": verdict.reason}
            except Exception as exc:
                # the judge is an advisory rung over an already-witnessed answer; a judge
                # that cannot produce a verdict is recorded, not fatal, so the run keeps
                # its answer (the same witnessed-not-fatal contract as a failed task)
                payload = {"ok": None, "score": 0.0, "reason": f"judge failed: {type(exc).__name__}: {exc}"}
            self.ledger.append(
                actor="intent-judge",
                kind="intent_judgment",
                payload=payload,
                causal_parent=check.seq,
            )

    def _resolve_delivery(self, request: str, answer: str, parent_seq: int) -> tuple[str, int]:
        """Witness the delivery floor and, when it flags a dense answer, pull a verified
        tightening. The floor (forum.delivery.assess) is deterministic and always runs.
        If it flags and a reviser is configured, Forum pulls a tighter version and accepts
        it only if it is strictly shorter AND still covers the request's terms
        (forum.intent.coverage). That guard is lexical, not semantic: an accepted revision
        keeps every request term the original carried and drops none, but coverage cannot
        see content outside the request, so this is a floor on dropped terms, not a proof
        of preserved meaning. A revision that fails either test, or a reviser that crashes,
        is recorded and discarded; the floor never blocks. An accepted revision is
        witnessed as its own result entry (revised_from the original) so the run's last
        result is what shipped. Returns (answer to deliver, seq of the entry holding it).
        """
        d = assess(answer)
        check = self.ledger.append(
            actor="delivery",
            kind="delivery_check",
            payload={
                "words": d.words, "sentences": d.sentences,
                "mean_sentence_words": d.mean_sentence_words,
                "filler_ratio": d.filler_ratio, "flagged": d.flagged,
            },
            causal_parent=parent_seq,
        )
        if not d.flagged:
            return answer, parent_seq
        try:
            revised = self.reviser.revise(request, answer)
        except Exception as exc:
            self.ledger.append(
                actor="reviser", kind="revision",
                payload={"accepted": False, "reason": f"reviser failed: {type(exc).__name__}: {exc}"},
                causal_parent=check.seq,
            )
            return answer, parent_seq
        if revised is None:
            return answer, parent_seq
        after = assess(revised)
        cov_before, _ = coverage(request, answer)
        cov_after, _ = coverage(request, revised)
        accepted = after.words < d.words and cov_after >= cov_before
        rev = self.ledger.append(
            actor="reviser", kind="revision",
            payload={
                "accepted": accepted,
                "words_before": d.words, "words_after": after.words,
                "coverage_before": round(cov_before, 4), "coverage_after": round(cov_after, 4),
            },
            causal_parent=check.seq,
        )
        if not accepted:
            return answer, parent_seq
        # the accepted, tighter answer is what ships; witness it as its own result entry
        # so the run's last result is the delivered answer, not the pre-revision one
        delivered = self.ledger.append(
            actor="synthesizer", kind="result",
            payload={"answer": revised, "revised_from": parent_seq}, causal_parent=rev.seq,
        )
        return revised, delivered.seq

    def _witness_verification(self, request: str, answer: str, parent_seq: int) -> None:
        """Witness an external verifier's verdict on the answer, if one is configured.

        The peer of context: where a ContextProvider feeds organized knowledge in
        before the run, a VerifierProvider checks the answer after it. The default
        NullVerifier abstains (returns None), so Forum stands alone and nothing is
        witnessed. A verdict is recorded as its own entry chained to the answer; like
        the intent check it is a witnessed signal and never blocks the run, leaving
        what to do about a refuted answer to policy.
        """
        try:
            verification = self.verifier.verify(request, answer)
        except Exception as exc:
            # the verifier is external, advisory code over an already-witnessed answer; a
            # verifier that crashes is recorded as could-not-decide, not fatal, so the run
            # keeps its answer (the same witnessed-not-fatal contract as the intent-judge)
            self.ledger.append(
                actor="verifier",
                kind="verification",
                payload={"ok": None, "detail": f"verifier failed: {type(exc).__name__}: {exc}", "source": ""},
                causal_parent=parent_seq,
            )
            return
        if verification is None:
            return
        self.ledger.append(
            actor="verifier",
            kind="verification",
            payload={"ok": verification.ok, "detail": verification.detail, "source": verification.source},
            causal_parent=parent_seq,
        )

    @staticmethod
    def _delivery_contract(route_frame, selected_profile: str | None) -> str:
        from forum.communication_contract import (
            build_communication_contract,
            communication_contract_text,
        )

        profile = selected_profile or route_frame.delivery_profile
        parts = [
            f"posture={route_frame.posture}",
            f"profile={profile}",
            f"domain={route_frame.domain}",
            f"intent={route_frame.intent}",
        ]
        if route_frame.proof_lane is not None:
            parts.append(f"proof_lane={route_frame.proof_lane}")
        if route_frame.domain_lane is not None:
            parts.append(f"domain_lane={route_frame.domain_lane}")
        parts.append(route_frame.human_contract)
        parts.append(
            communication_contract_text(
                build_communication_contract(
                    domain=route_frame.domain,
                    intent=route_frame.intent,
                    posture=route_frame.posture,
                    profile=profile,
                    human_contract=route_frame.human_contract,
                    proof_lane=route_frame.proof_lane,
                    domain_lane=route_frame.domain_lane,
                )
            )
        )
        return "\n".join(parts)

    async def assign(self, task: str, *, parent_seq: int | None = None) -> str:
        """Resolve one task's agent through the routing ladder, witnessed.

        Tier-0 lexical routing decides when it can; otherwise it escalates to the
        Tier-2 Classifier. The route, and any classification, are both recorded.
        """
        from forum.route_frame import derive_route_frame, frame_payload

        routed = self.route(task)
        frame = derive_route_frame(task, routed, self.roster)
        route_entry = self.ledger.append(
            actor="router",
            kind="route",
            payload={
                "task": task,
                "decided": routed.decided,
                "confidence": routed.confidence,
                "frame": frame_payload(frame),
            },
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
