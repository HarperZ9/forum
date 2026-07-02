import asyncio

from forum.context import NullContextProvider
from forum.engine import Orchestrator
from forum.executor import Result
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.roster import loads

ROSTER = loads(
    """
[[agent]]
name="backend"
category="engineering"
domain="apis"
keywords=["api"]
model_tier="capable"
executor="echo"
"""
)


class _Recorder:
    def __init__(self):
        self.prompts = {}

    async def run(self, assignment):
        self.prompts[assignment.agent] = assignment.instruction
        a = assignment.agent
        if a == "coordinator":
            out = '{"tasks": [{"id": "T1", "agent": "backend", "instruction": "build", "depends_on": []}]}'
        elif a == "validator":
            out = '{"ok": true, "score": 0.9, "reason": "ok"}'
        elif a == "synthesizer":
            out = "answer"
        else:
            out = "did it"
        return Result(assignment.task_id, assignment.agent, out)


class _Ctx:
    def context(self, request):
        return "ACME uses Postgres. The api lane owns auth."


def _orch(executor, provider=None):
    ticks = iter(float(t) for t in range(1, 1000))
    led = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        ROSTER, led, executor,
        Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2),
        context_provider=provider,
    )
    return led, orch


def test_null_provider_is_the_default_and_witnesses_no_context():
    assert NullContextProvider().context("anything") == ""
    led, orch = _orch(_Recorder())
    asyncio.run(orch.submit("build the api"))
    assert led.query(kind="context") == []  # no provider, no context entry


def test_provider_context_is_witnessed_and_fed_to_the_plan():
    rec = _Recorder()
    led, orch = _orch(rec, provider=_Ctx())
    asyncio.run(orch.submit("build the api"))

    ctx_entries = led.query(kind="context")
    request_ctx = ctx_entries[0]                              # the request-level context, before planning
    body = led._s.get_payload(request_ctx.payload_hash)
    assert "Postgres" in body["context"]                      # the context was recorded
    assert "Postgres" in rec.prompts["coordinator"]           # and fed into the plan prompt
    plan_entry = led.query(kind="plan")[0]
    assert plan_entry.causal_parent == request_ctx.seq        # request -> context -> plan
    # per-task context is also witnessed now: the T1 task pulls its own context
    assert any(led._s.get_payload(e.payload_hash).get("task") == "T1" for e in ctx_entries)
    assert led.verify(deep=True) is True


def test_request_context_budget_trims_before_planning():
    from forum.context_budget import ContextBudget

    class _BigCtx:
        def context(self, request):
            return "abcdefghij" * 10

    rec = _Recorder()
    led, orch = _orch(rec, provider=_BigCtx())
    asyncio.run(orch.submit("build the api", context_budget=ContextBudget(max_request_tokens=2)))

    budget_entries = led.query(kind="context_budget")
    assert len(budget_entries) >= 1
    budget_body = led.get_payload(budget_entries[0].payload_hash)
    assert budget_body["schema"] == "forum.context-pressure/v1"
    assert budget_body["source"] == "request"
    assert budget_body["action"] == "trimmed"
    assert budget_body["reason"] == "max_request_tokens"

    request_ctx = next(
        e for e in led.query(kind="context") if "task" not in led.get_payload(e.payload_hash)
    )
    ctx = led.get_payload(request_ctx.payload_hash)["context"]
    assert ctx == "abcdefgh"
    assert "abcdefgh" in rec.prompts["coordinator"]
    assert "abcdefghijabcdefghij" not in rec.prompts["coordinator"]
    assert led.verify(deep=True) is True


def test_request_context_budget_can_omit_context_and_keep_planning():
    from forum.context_budget import ContextBudget

    class _Ctx:
        def context(self, request):
            return "context"

    rec = _Recorder()
    led, orch = _orch(rec, provider=_Ctx())
    asyncio.run(orch.submit("build the api", context_budget=ContextBudget(max_total_tokens=0)))

    bodies = [led.get_payload(e.payload_hash) for e in led.query(kind="context_budget")]
    assert bodies[0]["source"] == "request"
    assert bodies[0]["action"] == "omitted"
    assert bodies[0]["reason"] == "max_total_tokens"
    assert "Context (organized knowledge to use)" not in rec.prompts["coordinator"]
    assert led.verify(deep=True) is True


def test_synthesis_result_budget_trims_prompt_but_keeps_full_result():
    from forum.context_budget import ContextBudget

    class _LongResultRecorder(_Recorder):
        async def run(self, assignment):
            self.prompts[assignment.agent] = assignment.instruction
            if assignment.agent == "backend":
                return Result(assignment.task_id, assignment.agent, "abcdefghijklmnop")
            return await super().run(assignment)

    rec = _LongResultRecorder()
    led, orch = _orch(rec)
    asyncio.run(orch.submit("build the api", context_budget=ContextBudget(max_upstream_tokens=2)))

    synth_prompt = rec.prompts["synthesizer"]
    assert "- T1: abcdefgh" in synth_prompt
    assert "abcdefghijklmnop" not in synth_prompt

    task_result = next(
        led.get_payload(e.payload_hash)
        for e in led.query(kind="result")
        if led.get_payload(e.payload_hash).get("id") == "T1"
    )
    assert task_result["output"] == "abcdefghijklmnop"

    budget_bodies = [led.get_payload(e.payload_hash) for e in led.query(kind="context_budget")]
    synth_budget = next(body for body in budget_bodies if body["label"] == "T1->synthesizer")
    assert synth_budget["source"] == "upstream"
    assert synth_budget["action"] == "trimmed"
    assert synth_budget["reason"] == "max_upstream_tokens"
    assert led.verify(deep=True) is True
