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
