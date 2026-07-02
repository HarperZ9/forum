import asyncio

from forum.dispatch import augment_with_upstream, dispatch_plan
from forum.executor import EchoExecutor
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task


def make_ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def test_dispatch_runs_plan_and_witnesses_it():
    ledger = make_ledger()
    plan = Plan(
        (
            Task("T1", "backend", "schema", ()),
            Task("T2", "backend", "endpoint", ("T1",)),
            Task("T3", "docs", "api docs", ("T2",)),
        )
    )
    results = asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), max_parallel=2))

    assert set(results) == {"T1", "T2", "T3"}
    assert results["T1"].output == "done: schema"
    assert len(ledger.query(kind="result")) == 3
    assert len(ledger.query(kind="task")) == 3
    assert ledger.verify(deep=True) is True


class _TrackingExecutor:
    """Instrumented executor: records the peak number of concurrently-running tasks."""

    def __init__(self):
        self.current = 0
        self.peak = 0

    async def run(self, assignment):
        from forum.executor import Result

        self.current += 1
        self.peak = max(self.peak, self.current)
        await asyncio.sleep(0)  # yield so a sibling task in the same wave can interleave
        self.current -= 1
        return Result(assignment.task_id, assignment.agent, f"done: {assignment.instruction}")


def test_independent_tasks_run_concurrently_and_are_witnessed():
    ledger = make_ledger()
    plan = Plan(
        (
            Task("A", "backend", "a", ()),
            Task("B", "frontend", "b", ()),
            Task("C", "docs", "c", ("A", "B")),
        )
    )
    ex = _TrackingExecutor()
    results = asyncio.run(dispatch_plan(plan, ledger, ex, max_parallel=2))

    assert set(results) == {"A", "B", "C"}
    assert ex.peak >= 2  # A and B were in flight at the same time
    assert ledger.verify(deep=True) is True
    assert plan.schedule()[0] == ["A", "B"]  # they share the first wave


class _RaisingExecutor:
    """Raises for task 'B' only; succeeds otherwise."""

    async def run(self, assignment):
        from forum.executor import Result

        if assignment.task_id == "B":
            raise RuntimeError("boom")
        return Result(assignment.task_id, assignment.agent, "ok")


def test_failing_task_is_witnessed_and_siblings_survive():
    ledger = make_ledger()
    plan = Plan(
        (
            Task("A", "x", "a", ()),
            Task("B", "x", "b", ()),
            Task("C", "x", "c", ("A", "B")),
        )
    )
    results = asyncio.run(dispatch_plan(plan, ledger, _RaisingExecutor(), max_parallel=2))

    assert results["A"].ok is True
    assert results["B"].ok is False
    assert "boom" in results["B"].output
    assert results["C"].ok is True
    assert len(ledger.query(kind="result")) == 3  # every task got a witnessed result
    assert ledger.verify(deep=True) is True


class _EchoSawExecutor:
    """Echoes the exact instruction it received, so injected upstream output is visible."""

    async def run(self, assignment):
        from forum.executor import Result

        return Result(assignment.task_id, assignment.agent, assignment.instruction)


def _task_entry(ledger, tid):
    return next(
        e for e in ledger.query(kind="task") if ledger.get_payload(e.payload_hash)["id"] == tid
    )


def test_data_edge_feeds_upstream_output_downstream():
    ledger = make_ledger()
    plan = Plan(
        (
            Task("T1", "backend", "schema", ()),
            Task("T2", "backend", "endpoint", ("T1",)),  # data edge (the default)
        )
    )
    results = asyncio.run(dispatch_plan(plan, ledger, _EchoSawExecutor(), max_parallel=2))

    assert "Upstream results you build on:" in results["T2"].output
    assert "T1: schema" in results["T2"].output            # T2 saw T1's output
    body = ledger.get_payload(_task_entry(ledger, "T2").payload_hash)
    assert body["data_from"] == ["T1"]                     # witnessed: T2 consumed T1
    assert body["instruction"] == "endpoint"              # the witnessed instruction stays original
    assert ledger.verify(deep=True) is True


def test_order_edge_does_not_feed_output():
    ledger = make_ledger()
    plan = Plan(
        (
            Task("T1", "backend", "schema", ()),
            Task("T2", "ops", "notify", ("T1",), frozenset({"T1"})),  # order edge
        )
    )
    results = asyncio.run(dispatch_plan(plan, ledger, _EchoSawExecutor(), max_parallel=2))

    assert results["T2"].output == "notify"                # nothing injected
    assert ledger.get_payload(_task_entry(ledger, "T2").payload_hash)["data_from"] == []


class _FailFirstExecutor:
    """T1 fails (ok=False); everyone else echoes the instruction they received."""

    async def run(self, assignment):
        from forum.executor import Result

        if assignment.task_id == "T1":
            return Result("T1", assignment.agent, "boom", ok=False)
        return Result(assignment.task_id, assignment.agent, assignment.instruction)


def test_failed_upstream_is_not_fed_downstream():
    ledger = make_ledger()
    plan = Plan(
        (
            Task("T1", "backend", "schema", ()),
            Task("T2", "backend", "endpoint", ("T1",)),  # data edge on a FAILING upstream
        )
    )
    results = asyncio.run(dispatch_plan(plan, ledger, _FailFirstExecutor(), max_parallel=2))

    assert results["T1"].ok is False
    assert results["T2"].output == "endpoint"   # no error injected; T2 ran on its own instruction
    assert "boom" not in results["T2"].output
    body = ledger.get_payload(_task_entry(ledger, "T2").payload_hash)
    assert body["data_from"] == []              # a failed upstream is not "consumed"
    # the edge is still declared in the plan, so edges-minus-data_from is a witnessed signal
    edges = ledger.get_payload(ledger.query(kind="plan")[0].payload_hash)["edges"]
    assert {"from": "T1", "to": "T2", "type": "data"} in edges
    assert ledger.verify(deep=True) is True


def test_done_criteria_are_sent_to_worker_and_witnessed():
    ledger = make_ledger()
    plan = Plan(
        (
            Task(
                "T1",
                "backend",
                "build",
                (),
                done_when=("tests pass", "migration documented"),
            ),
        )
    )
    results = asyncio.run(dispatch_plan(plan, ledger, _EchoSawExecutor(), max_parallel=2))

    assert results["T1"].output == (
        "build\n\n"
        "Done criteria:\n"
        "- tests pass\n"
        "- migration documented"
    )
    body = ledger.get_payload(_task_entry(ledger, "T1").payload_hash)
    assert body["instruction"] == "build"
    assert body["done_when"] == ["tests pass", "migration documented"]
    assert ledger.verify(deep=True) is True


def test_plan_entry_witnesses_typed_edges():
    ledger = make_ledger()
    plan = Plan(
        (
            Task("T1", "x", "a", ()),
            Task("T2", "x", "b", ("T1",)),                     # data
            Task("T3", "x", "c", ("T1",), frozenset({"T1"})),  # order
        )
    )
    asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), max_parallel=2))
    edges = ledger.get_payload(ledger.query(kind="plan")[0].payload_hash)["edges"]
    assert {"from": "T1", "to": "T2", "type": "data"} in edges
    assert {"from": "T1", "to": "T3", "type": "order"} in edges


class _FailT2:
    """T1 succeeds; T2 fails. (Used to leave a run half-done for resume.)"""

    async def run(self, assignment):
        from forum.executor import Result

        if assignment.task_id == "T2":
            return Result("T2", assignment.agent, "boom", ok=False)
        return Result(assignment.task_id, assignment.agent, f"done: {assignment.instruction}")


def test_resume_reuses_completed_results_and_reruns_the_rest():
    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    asyncio.run(dispatch_plan(plan, ledger, _FailT2(), max_parallel=2))  # T1 ok, T2 failed

    results = asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), max_parallel=2, resume=True))
    assert results["T1"].output == "done: a"          # reused, not re-executed (Echo would say "done: a" too,
    assert results["T1"].witnessed_seq is not None      #  but it points at the ORIGINAL result entry)
    assert results["T2"].ok is True and results["T2"].output.startswith("done: b")  # re-run (was failed)
    assert "T1: done: a" in results["T2"].output       # the reused upstream's output flowed into the re-run
    reused = ledger.query(kind="resume")
    assert len(reused) == 1
    assert ledger.get_payload(reused[0].payload_hash)["reused"] == ["T1"]
    assert ledger.verify(deep=True) is True


def test_resume_with_no_prior_results_runs_everything():
    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "a", ()),))
    results = asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), resume=True))
    assert results["T1"].output == "done: a"
    assert ledger.query(kind="resume") == []  # nothing to reuse, no resume entry


def test_checkpoint_each_wave_witnesses_a_checkpoint_per_wave():
    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))  # two waves
    asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), max_parallel=2, checkpoint_each_wave=True))
    cps = ledger.query(kind="checkpoint")
    assert [ledger.get_payload(e.payload_hash)["wave"] for e in cps] == [0, 1]
    assert all(len(ledger.get_payload(e.payload_hash)["root"]) == 64 for e in cps)
    assert ledger.verify(deep=True) is True


def test_fully_completed_plan_resumed_reuses_everything():
    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), max_parallel=2))  # all succeed
    tasks_before = len(ledger.query(kind="task"))
    results = asyncio.run(dispatch_plan(plan, ledger, EchoExecutor(), max_parallel=2, resume=True))
    assert set(results) == {"T1", "T2"}
    assert len(ledger.query(kind="task")) == tasks_before  # nothing re-run, no new task entries
    reused = ledger.get_payload(ledger.query(kind="resume")[0].payload_hash)["reused"]
    assert reused == ["T1", "T2"]
    assert ledger.verify(deep=True) is True


def test_augment_caps_a_large_upstream_for_prompt_efficiency():
    from forum.executor import Result

    task = Task("T2", "x", "build", ("T1",))
    results = {"T1": Result("T1", "x", "y" * 100, ok=True)}
    instruction, data_from = augment_with_upstream(task, results, max_chars=10)
    assert data_from == ["T1"]
    assert "truncated for prompt efficiency" in instruction
    assert "y" * 10 in instruction and "y" * 100 not in instruction  # capped, not the full output


def test_augment_cap_boundary_and_disable():
    from forum.executor import Result

    task = Task("T2", "x", "go", ("T1",))
    at = augment_with_upstream(task, {"T1": Result("T1", "x", "y" * 10, ok=True)}, max_chars=10)[0]
    assert "truncated" not in at and "y" * 10 in at          # exactly at cap: not truncated
    over = augment_with_upstream(task, {"T1": Result("T1", "x", "y" * 11, ok=True)}, max_chars=10)[0]
    assert "truncated for prompt efficiency" in over          # one over cap: truncated
    big = augment_with_upstream(task, {"T1": Result("T1", "x", "y" * 100, ok=True)}, max_chars=10**9)[0]
    assert "truncated" not in big and "y" * 100 in big        # a huge cap effectively disables it


def test_dispatch_plan_max_upstream_chars_tunes_the_cap():
    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    results = asyncio.run(dispatch_plan(plan, ledger, _BigT1(), max_parallel=2, max_upstream_chars=100))
    assert "truncated for prompt efficiency" in results["T2"].output
    assert len(results["T2"].output) < 500  # tuned far below the 8192 default


class _BigT1:
    """T1 emits a large output; everyone else echoes the instruction they received."""

    async def run(self, assignment):
        from forum.executor import Result

        if assignment.task_id == "T1":
            return Result("T1", assignment.agent, "x" * 10000)
        return Result(assignment.task_id, assignment.agent, assignment.instruction)


def test_capped_injection_shrinks_the_prompt_but_the_record_keeps_the_full_output():
    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))  # T2 data-depends on T1
    results = asyncio.run(dispatch_plan(plan, ledger, _BigT1(), max_parallel=2))

    assert "truncated for prompt efficiency" in results["T2"].output  # T2's prompt got a capped T1
    assert len(results["T2"].output) < 10000  # bounded, not the full 10k
    t1_result = next(
        ledger.get_payload(e.payload_hash)
        for e in ledger.query(kind="result")
        if ledger.get_payload(e.payload_hash).get("id") == "T1"
    )
    assert t1_result["output"] == "x" * 10000  # the full output is still witnessed
    assert ledger.verify(deep=True) is True


class _PerTaskContext:
    """A ContextProvider that returns context tailored to each task's instruction."""

    def context(self, text):
        return f"ctx for: {text}"


def test_per_task_context_is_injected_witnessed_and_chained():
    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "do the thing", ()),))
    results = asyncio.run(dispatch_plan(plan, ledger, _EchoSawExecutor(), context_provider=_PerTaskContext()))
    assert "Context for this task:" in results["T1"].output  # the agent saw its context
    assert "ctx for: do the thing" in results["T1"].output
    ctx_bodies = [ledger.get_payload(e.payload_hash) for e in ledger.query(kind="context")]
    assert any(c.get("task") == "T1" for c in ctx_bodies)    # witnessed, tied to the task
    assert ledger.get(_task_entry(ledger, "T1").causal_parent).kind == "context"  # task chained to its context
    assert ledger.verify(deep=True) is True


def test_no_per_task_context_without_a_provider():
    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "do the thing", ()),))
    results = asyncio.run(dispatch_plan(plan, ledger, _EchoSawExecutor()))
    assert "Context for this task" not in results["T1"].output
    assert ledger.query(kind="context") == []  # default: no per-task context


def test_per_task_context_is_capped():
    ledger = make_ledger()

    class _Big:
        def context(self, text):
            return "c" * 10000

    plan = Plan((Task("T1", "x", "go", ()),))
    results = asyncio.run(dispatch_plan(plan, ledger, _EchoSawExecutor(), context_provider=_Big(), max_upstream_chars=100))
    assert "truncated for prompt efficiency" in results["T1"].output
    assert len(results["T1"].output) < 500


def test_each_task_in_a_wave_gets_its_own_context():
    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "alpha", ()), Task("T2", "x", "beta", ())))  # one concurrent wave
    asyncio.run(dispatch_plan(plan, ledger, _EchoSawExecutor(), context_provider=_PerTaskContext(), max_parallel=2))
    bodies = {b["task"]: b["context"] for b in (ledger.get_payload(e.payload_hash) for e in ledger.query(kind="context"))}
    assert bodies == {"T1": "ctx for: alpha", "T2": "ctx for: beta"}  # each agent got its own
    assert ledger.get(_task_entry(ledger, "T1").causal_parent).kind == "context"
    assert ledger.get(_task_entry(ledger, "T2").causal_parent).kind == "context"
    assert ledger.verify(deep=True) is True  # both context+task append pairs survive concurrency


def test_empty_context_for_a_task_falls_back_to_the_plan_parent():
    ledger = make_ledger()

    class _SelectiveCtx:
        def context(self, text):
            return "ctx for go" if text == "go" else ""  # "" for the other task

    plan = Plan((Task("T1", "x", "go", ()), Task("T2", "x", "skip", ())))
    results = asyncio.run(dispatch_plan(plan, ledger, _EchoSawExecutor(), context_provider=_SelectiveCtx(), max_parallel=2))
    assert ledger.get(_task_entry(ledger, "T1").causal_parent).kind == "context"  # T1 got context
    assert ledger.get(_task_entry(ledger, "T2").causal_parent).kind == "plan"     # "" -> chained straight to plan
    assert "Context for this task" not in results["T2"].output                    # nothing injected for T2
    bodies = [b["task"] for b in (ledger.get_payload(e.payload_hash) for e in ledger.query(kind="context"))]
    assert bodies == ["T1"]  # only T1 produced a context entry
    assert ledger.verify(deep=True) is True


def test_resume_and_checkpoint_together():
    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    asyncio.run(dispatch_plan(plan, ledger, _FailT2(), max_parallel=2))  # T2 fails
    asyncio.run(
        dispatch_plan(plan, ledger, EchoExecutor(), max_parallel=2, resume=True, checkpoint_each_wave=True)
    )
    assert len(ledger.query(kind="resume")) == 1
    assert len(ledger.query(kind="checkpoint")) == 2  # both waves of the resume run checkpointed
    assert ledger.verify(deep=True) is True


def test_per_task_context_budget_trims_and_witnesses_pressure():
    from forum.context_budget import ContextBudget

    ledger = make_ledger()

    class _Big:
        def context(self, text):
            return "abcdefghijklmnop"

    plan = Plan((Task("T1", "x", "go", ()),))
    results = asyncio.run(
        dispatch_plan(
            plan,
            ledger,
            _EchoSawExecutor(),
            context_provider=_Big(),
            context_budget=ContextBudget(max_task_tokens=2),
        )
    )
    assert "Context for this task:" in results["T1"].output
    assert "abcdefgh" in results["T1"].output
    assert "abcdefghijklmnop" not in results["T1"].output
    bodies = [ledger.get_payload(e.payload_hash) for e in ledger.query(kind="context_budget")]
    assert any(b["source"] == "task" and b["action"] == "trimmed" for b in bodies)
    assert ledger.verify(deep=True) is True


def test_per_task_context_budget_omits_context_when_total_is_spent():
    from forum.context_budget import ContextBudget

    ledger = make_ledger()

    class _Big:
        def context(self, text):
            return "abcd"

    plan = Plan((Task("T1", "x", "go", ()),))
    results = asyncio.run(
        dispatch_plan(
            plan,
            ledger,
            _EchoSawExecutor(),
            context_provider=_Big(),
            context_budget=ContextBudget(max_total_tokens=0),
        )
    )
    assert "Context for this task:" not in results["T1"].output
    budget_body = ledger.get_payload(ledger.query(kind="context_budget")[0].payload_hash)
    assert budget_body["source"] == "task"
    assert budget_body["action"] == "omitted"
    assert budget_body["reason"] == "max_total_tokens"
    assert ledger.get(_task_entry(ledger, "T1").causal_parent).kind == "plan"
    assert ledger.verify(deep=True) is True


def test_upstream_context_budget_trims_prompt_but_keeps_full_result():
    from forum.context_budget import ContextBudget

    ledger = make_ledger()
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    results = asyncio.run(
        dispatch_plan(
            plan,
            ledger,
            _BigT1(),
            max_parallel=2,
            context_budget=ContextBudget(max_upstream_tokens=2),
        )
    )
    assert "truncated for prompt efficiency" in results["T2"].output
    assert "x" * 8 in results["T2"].output
    assert "x" * 10000 not in results["T2"].output
    budget_bodies = [ledger.get_payload(e.payload_hash) for e in ledger.query(kind="context_budget")]
    assert any(b["source"] == "upstream" and b["label"] == "T1->T2" for b in budget_bodies)
    t1_result = next(
        ledger.get_payload(e.payload_hash)
        for e in ledger.query(kind="result")
        if ledger.get_payload(e.payload_hash).get("id") == "T1"
    )
    assert t1_result["output"] == "x" * 10000


def test_dispatch_records_selected_tier_model_identity():
    from forum.executor import Result
    from forum.roster import load_default
    from forum.runtime import TieredExecutor

    class _Named:
        def __init__(self, model_id):
            self.model_id = model_id

        async def run(self, assignment):
            return Result(assignment.task_id, assignment.agent, assignment.instruction)

    ledger = make_ledger()
    plan = Plan((
        Task("T1", "backend", "build", ()),
        Task("T2", "technical-writing", "docs", ()),
    ))
    executor = TieredExecutor(
        load_default(),
        _Named("default-local"),
        tiers={"capable": _Named("capable-local"), "cheap": _Named("cheap-local")},
    )

    asyncio.run(dispatch_plan(plan, ledger, executor, max_parallel=2))

    models = {
        body["id"]: body["model"]
        for body in (ledger.get_payload(e.payload_hash) for e in ledger.query(kind="result"))
    }
    assert models == {"T1": "capable-local", "T2": "cheap-local"}
