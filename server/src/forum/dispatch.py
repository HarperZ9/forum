from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Callable

from forum.context import ContextProvider
from forum.context_budget import (
    ContextBudget,
    ContextBudgetMeter,
    ContextPressure,
    apply_context_budget,
    pressure_payload,
)
from forum.executor import Assignment, Executor, Result, assignment_model_id
from forum.gates import (
    GatePolicy,
    decision_entry,
    expire_gate,
    gate_edits,
    gate_resolution,
)
from forum.ledger import Ledger
from forum.plan import Plan, Task
from forum.run_lineage import (
    plan_digest,
    resume_lineage,
    wave_digest,
    wave_instructions,
)

# Per-upstream cap on injected output, to bound prompt growth down a deep or wide
# plan. Generous enough to leave normal outputs untouched; only runaway gets trimmed.
DEFAULT_MAX_UPSTREAM_CHARS = 8192


def augment_with_upstream(
    task: Task, results: dict[str, Result], *, max_chars: int = DEFAULT_MAX_UPSTREAM_CHARS
) -> tuple[str, list[str]]:
    """Feed a task's data-dependency outputs into its instruction.

    Returns ``(instruction_for_the_executor, the upstream ids actually injected)``. A
    data edge feeds the upstream's witnessed output into the downstream task so it can
    build on real work; an order edge only sequences and injects nothing. A failed
    upstream (ok=False) is not injected: the engine never treats a failure as usable
    work, so a downstream is not handed an error as build-on material, and the returned
    data_from lists only upstreams actually consumed. A data edge whose upstream failed
    thus appears in the plan's edges but not in the downstream's data_from; that
    divergence is a witnessed signal, not a bug.

    Each upstream output is capped at ``max_chars`` to bound prompt growth: an output
    over the cap is injected truncated with a marker, while the full output stays in the
    upstream's witnessed result entry, so the record loses nothing and only the prompt
    shrinks. Safe to call on concurrent tasks within a wave: no await (so it runs
    atomically between scheduling points) and it reads only the results of strictly
    earlier waves, which the wave barrier guarantees are complete. Deterministic:
    upstreams are injected in depends_on order, deduplicated.
    """
    parts: list[str] = []
    data_from: list[str] = []
    for dep in task.data_deps:
        up = results.get(dep)
        if up is not None and up.ok and dep not in data_from:
            output = up.output
            if len(output) > max_chars:
                omitted = len(output) - max_chars
                output = output[:max_chars] + f"\n... [truncated for prompt efficiency, {omitted} chars omitted; full output is witnessed]"
            parts.append(f"- {dep}: {output}")
            data_from.append(dep)
    instruction = task.contract_instruction()
    if not parts:
        return instruction, []
    return instruction + "\n\nUpstream results you build on:\n" + "\n".join(parts), data_from


def augment_with_upstream_budgeted(
    task: Task,
    results: dict[str, Result],
    *,
    context_budget: ContextBudget,
    context_meter: ContextBudgetMeter,
) -> tuple[str, list[str], list[ContextPressure]]:
    parts: list[str] = []
    data_from: list[str] = []
    pressures: list[ContextPressure] = []
    for dep in task.data_deps:
        up = results.get(dep)
        if up is None or not up.ok or dep in data_from:
            continue
        output, pressure = apply_context_budget(
            "upstream", f"{dep}->{task.id}", up.output, context_budget, context_meter
        )
        pressures.append(pressure)
        if not output:
            continue
        if pressure.action == "trimmed":
            omitted = pressure.original_bytes - pressure.admitted_bytes
            output = output + (
                f"\n... [truncated for prompt efficiency, {omitted} bytes omitted; "
                "full output is witnessed]"
            )
        parts.append(f"- {dep}: {output}")
        data_from.append(dep)
    instruction = task.contract_instruction()
    if not parts:
        return instruction, [], pressures
    return instruction + "\n\nUpstream results you build on:\n" + "\n".join(parts), data_from, pressures


def _completed_results(ledger: Ledger, ids: set[str]) -> dict[str, tuple[str, int]]:
    """Map each task id with a witnessed successful result to (output, that result's seq).

    Reads the durable ledger so a resumed run can reuse work already done. The latest
    ok=True result per id wins (seq order). Only successful results are reused; a task
    with no result, or only a failed one, is left to run again. No model is involved:
    resume reuses the verified record, it does not regenerate it.

    Resume assumes one ledger directory holds a single run lineage: task ids are matched
    across all prior entries, so do not resume a plan over a ledger populated by an
    unrelated plan that reuses the same ids.
    """
    done: dict[str, tuple[str, int]] = {}
    for e in ledger.query(kind="result"):
        body = ledger.get_payload(e.payload_hash)
        tid = body.get("id")
        if tid in ids and body.get("ok") is True:
            done[tid] = (body["output"], e.seq)
    return done


async def dispatch_plan(
    plan: Plan,
    ledger: Ledger,
    executor: Executor,
    *,
    max_parallel: int = 6,
    parent_seq: int | None = None,
    over_budget: Callable[[], bool] | None = None,
    resume: bool = False,
    checkpoint_each_wave: bool = False,
    max_upstream_chars: int = DEFAULT_MAX_UPSTREAM_CHARS,
    context_provider: ContextProvider | None = None,
    context_budget: ContextBudget | None = None,
    context_meter: ContextBudgetMeter | None = None,
    gates: GatePolicy | None = None,
) -> dict[str, Result]:
    """Run a plan's waves through the executor, witnessing every step.

    Appends a ``plan`` entry, then a ``task`` + ``result`` entry per task with
    causal links. Each wave runs concurrently (bounded by ``max_parallel``);
    waves run in dependency order.

    With a ``context_provider``, each task pulls fresh, task-specific context from
    the brain (the ContextProvider seam) before it runs: the context is capped (like
    upstream data), witnessed as its own entry, and the task is chained to it, so a
    parallel or looped agent gets up-to-date context routed to it and the record
    shows exactly what shaped each task. Forum pulls and witnesses the context; it
    never generates it. The pull is synchronous and runs once per task inside the
    wave, so a provider that blocks (does I/O) serializes the wave; keep context()
    fast and offline, as the Protocol advises.

    With ``resume=True`` a task that already has a witnessed successful result in
    the ledger is reused, not re-run, and a ``resume`` entry records which were
    reused; the ledger is the resume state, so no work and no model call is spent
    twice (a reused result reflects the current plan's agent, while its witnessed_seq
    points at the original entry that produced it). With
    ``checkpoint_each_wave=True`` a ``checkpoint`` entry (the Merkle
    root so far) is witnessed and the ledger synced after each wave, a re-checkable
    savepoint and the durability point for batched storage.

    With a ``gates`` GatePolicy, a wave listed in ``gates.gated_waves`` pauses for
    human approval at its boundary: BEFORE that wave is dispatched, dispatch reads
    the ledger (a pure query, no callback) for a resolution keyed to
    (run_seq, wave) and to the wave's content: run_seq is this run's own plan
    entry seq, and a resume reuses the key of the run whose plan has the same
    digest (a different or rewritten plan starts a run of its own). Only a
    decision chained to a ``gate_pending`` that showed this wave's content counts.
    With no decision it appends a ``gate_pending`` (the task ids, their
    instructions and a ``wave_digest``), syncs, and returns early so the gated
    wave and everything downstream stay un-run (no result entry for them); the
    operator resolves the gate via gates.resolve_gate (CLI/HTTP/MCP) and
    re-invokes with resume=True over the same ledger, which reuses the completed
    waves and re-reaches the boundary. A ``gate_rejected`` appends a
    ``gate_stopped`` and returns without running the wave; a ``gate_approved`` /
    ``gate_edited`` proceeds, an edit rewriting instructions of that wave's tasks
    only. The gate reads and the gate_pending / gate_stopped appends stay
    await-free, at the wave boundary, like the checkpoint.
    """
    results: dict[str, Result] = {}
    if context_budget is not None and context_meter is None:
        context_meter = ContextBudgetMeter()
    sem = asyncio.Semaphore(max_parallel)
    by_id = {t.id: t for t in plan.tasks}
    waves = plan.schedule()
    completed = _completed_results(ledger, set(by_id)) if resume else {}

    edges = [
        {"from": dep, "to": t.id, "type": "order" if dep in t.order_deps else "data"}
        for t in plan.tasks
        for dep in t.depends_on
    ]
    # run_seq keys gate entries to one run. A fresh run is keyed to its own plan
    # entry, so a decision recorded for an earlier run, or ahead of time, never
    # answers its gates. A resume continues the latest run of this same plan (same
    # digest): it reuses that run's key and records it on its own plan entry, so
    # gates resolved against the run are found again at their boundary. A resume
    # with a different plan finds no run and starts one of its own.
    digest = plan_digest(plan)
    lineage = resume_lineage(ledger, digest, waves) if resume else None
    plan_payload: dict[str, object] = {"waves": waves, "edges": edges, "plan_digest": digest}
    if lineage is not None:
        plan_payload["run_seq"] = lineage
    plan_entry = ledger.append(
        actor="dispatch", kind="plan", payload=plan_payload, causal_parent=parent_seq
    )
    run_seq = plan_entry.seq if lineage is None else lineage
    if completed:
        ledger.append(
            actor="dispatch", kind="resume",
            payload={"reused": sorted(completed)}, causal_parent=plan_entry.seq,
        )

    async def run_task(task: Task) -> None:
        async with sem:
            if task.id in completed:
                # reuse the verified result already in the ledger; do not re-run or re-witness
                output, seq = completed[task.id]
                results[task.id] = Result(task.id, task.agent, output, ok=True, witnessed_seq=seq)
                return
            # a data edge feeds its upstream's output into this task; an order edge does not
            if context_budget is not None and context_meter is not None:
                instruction, data_from, upstream_pressures = augment_with_upstream_budgeted(
                    task, results, context_budget=context_budget, context_meter=context_meter
                )
                for pressure in upstream_pressures:
                    ledger.append(
                        actor="context-budget",
                        kind="context_budget",
                        payload=pressure_payload(pressure, context_budget, context_meter),
                        causal_parent=plan_entry.seq,
                    )
            else:
                instruction, data_from = augment_with_upstream(task, results, max_chars=max_upstream_chars)
            # fresh, task-specific context pulled from the brain, capped and witnessed; the
            # task is chained to it so the record shows what shaped it (Forum routes the
            # context to the agent, it never generates it)
            task_parent = plan_entry.seq
            if context_provider is not None:
                # INVARIANT: no await between here and the task append below. context() is
                # sync by contract (the ContextProvider Protocol), so the context pull and
                # the two appends stay one atomic, no-yield window; an await here would let
                # concurrent run_tasks interleave and corrupt seq/prev_hash.
                ctx = context_provider.context(task.instruction)
                if context_budget is not None and context_meter is not None:
                    ctx, pressure = apply_context_budget("task", task.id, ctx, context_budget, context_meter)
                    if pressure.original_tokens > 0:
                        ledger.append(
                            actor="context-budget",
                            kind="context_budget",
                            payload=pressure_payload(pressure, context_budget, context_meter),
                            causal_parent=plan_entry.seq,
                        )
                elif ctx and len(ctx) > max_upstream_chars:
                    # A barer marker than upstream's on purpose: the full context is NOT
                    # witnessed (only this capped slice is), so do not claim it is.
                    ctx = ctx[:max_upstream_chars] + "\n... [truncated for prompt efficiency]"
                if ctx:
                    task_parent = ledger.append(
                        actor="context", kind="context",
                        payload={"task": task.id, "context": ctx}, causal_parent=plan_entry.seq,
                    ).seq
                    instruction = instruction + "\n\nContext for this task:\n" + ctx
            task_payload = {
                "id": task.id,
                "agent": task.agent,
                "instruction": task.instruction,
                "data_from": data_from,
            }
            if task.done_when:
                task_payload["done_when"] = list(task.done_when)
            assigned = ledger.append(
                actor="dispatch",
                kind="task",
                payload=task_payload,
                causal_parent=task_parent,
            )
            if over_budget is not None and over_budget():
                # budget is gone; witness the task without spending a model call
                result = Result(task.id, task.agent, "error: budget exceeded", ok=False)
            else:
                try:
                    result = await executor.run(Assignment(task.id, task.agent, instruction))
                except Exception as exc:
                    result = Result(task.id, task.agent, f"error: {exc}", ok=False)
            entry = ledger.append(
                actor=task.agent,
                kind="result",
                payload={
                    "id": task.id,
                    "output": result.output,
                    "ok": result.ok,
                    "model": assignment_model_id(executor, Assignment(task.id, task.agent, instruction)),
                },
                causal_parent=assigned.seq,
            )
            results[task.id] = dataclasses.replace(result, witnessed_seq=entry.seq)

    for i, wave in enumerate(waves):
        if gates is not None and i in gates.gated_waves:
            # Gate boundary: read the ledger (pure query, no await) for this wave's
            # resolution, then decide synchronously. run_seq is stable across resume;
            # content binds the decision to the exact tasks this gate shows.
            shown = [by_id[tid] for tid in wave]
            content = (wave_digest(shown), list(wave))
            resolution = gate_resolution(ledger, run_seq, i, content=content)
            if resolution is None or resolution == "pending":
                if resolution is None:
                    # No gate has fired yet: raise one and pause. Guarding on
                    # resolution is None (matched by run_seq+wave) means a resume
                    # that re-reaches a still-unresolved gate does not duplicate it.
                    payload: dict[str, object] = {
                        "run_seq": run_seq,
                        "wave": i,
                        "tasks": list(wave),
                        "instructions": wave_instructions(shown),
                        "wave_digest": content[0],
                        "question": gates.question,
                        "requested_by": "dispatch",
                    }
                    if gates.deadline_seconds is not None:
                        # Record an absolute deadline off the ledger's own clock so
                        # it advances on the same time base that stamps entry ts and
                        # is itself hashed into the witnessed gate_pending payload.
                        payload["on_expiry"] = gates.on_expiry
                        payload["deadline"] = float(ledger.clock()) + gates.deadline_seconds
                    ledger.append(
                        actor="dispatch", kind="gate_pending",
                        payload=payload, causal_parent=run_seq,
                    )
                    ledger.sync()
                else:
                    # Already pending: if a deadline was set and has lapsed with
                    # no operator decision, auto-resolve it (witnessed) and act on
                    # the result instead of blocking forever. No-op for unbounded
                    # gates or before the deadline.
                    expired = expire_gate(ledger, run_seq, i, clock=ledger.clock, content=content)
                    if expired is not None:
                        resolution = expired
                if resolution is None or resolution == "pending":
                    # pending (awaiting the operator, no lapsed deadline): stop here
                    # so the gated wave and everything downstream stay un-run
                    return results
            if resolution == "rejected":
                # Chain the stop to the decision that caused it: an operator's
                # gate_rejected, or (deadline lapsed with on_expiry=reject) the
                # witnessed gate_expired. Either way the stop is causally grounded.
                reject = decision_entry(
                    ledger, run_seq, i, ("gate_rejected", "gate_expired"), content=content
                )
                ledger.append(
                    actor="dispatch", kind="gate_stopped",
                    payload={"run_seq": run_seq, "wave": i, "reason": "gate rejected"},
                    causal_parent=reject.seq if reject is not None else run_seq,
                )
                ledger.sync()
                return results
            if resolution == "edited":
                # apply the operator's per-task instruction edits before dispatching;
                # a gate covers its own wave, so an edit naming another wave's task
                # is ignored (resolve_gate refuses one; this guards a raw entry)
                edits = gate_edits(ledger, run_seq, i, content=content)
                for tid, instruction in edits.items():
                    if tid in wave:
                        by_id[tid] = dataclasses.replace(by_id[tid], instruction=instruction)
            # approved / edited: fall through and dispatch the wave
        async with asyncio.TaskGroup() as tg:
            for tid in wave:
                tg.create_task(run_task(by_id[tid]))
        if checkpoint_each_wave:
            # a re-checkable savepoint after each wave, and the durability point for batched storage
            ledger.append(
                actor="dispatch", kind="checkpoint",
                payload={"wave": i, "root": ledger.checkpoint()}, causal_parent=plan_entry.seq,
            )
            ledger.sync()

    return results
