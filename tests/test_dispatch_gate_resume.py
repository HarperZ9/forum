import asyncio

from forum.dispatch import dispatch_plan
from forum.executor import EchoExecutor, Result
from forum.gates import GatePolicy
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task


def make_ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


class _EchoSaw:
    async def run(self, assignment):
        return Result(assignment.task_id, assignment.agent, assignment.instruction)


def _seed_run(led, decision_kind, *, edits=None):
    """Seed plan + witnessed T1 ok result + gate_pending{wave:1} + a decision entry."""
    req = led.append(actor="client", kind="request", payload={"tasks": ["T1", "T2"]})
    plan = led.append(
        actor="dispatch", kind="plan", payload={"waves": [["T1"], ["T2"]], "edges": []},
        causal_parent=req.seq,
    )
    task = led.append(
        actor="dispatch", kind="task",
        payload={"id": "T1", "agent": "x", "instruction": "a", "data_from": []},
        causal_parent=plan.seq,
    )
    led.append(
        actor="x", kind="result",
        payload={"id": "T1", "output": "done: a", "ok": True, "model": "EchoExecutor"},
        causal_parent=task.seq,
    )
    pend = led.append(
        actor="dispatch", kind="gate_pending",
        payload={"run_seq": plan.seq, "wave": 1, "tasks": ["T2"], "question": "q", "requested_by": "dispatch"},
        causal_parent=plan.seq,
    )
    payload = {"run_seq": plan.seq, "wave": 1, "approver": "op"}
    if decision_kind == "gate_edited":
        payload["edits"] = edits or {}
        payload["note"] = ""
    elif decision_kind == "gate_approved":
        payload["note"] = ""
    led.append(actor="operator", kind=decision_kind, payload=payload, causal_parent=pend.seq)
    return plan.seq


def _result_body(led, tid):
    for e in led.query(kind="result"):
        body = led.get_payload(e.payload_hash)
        if body.get("id") == tid:
            return body
    return None


def test_approve_resume_reuses_t1_and_runs_the_gated_wave():
    ledger = make_ledger()
    _seed_run(ledger, "gate_approved")
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))

    results = asyncio.run(
        dispatch_plan(plan, ledger, EchoExecutor(), resume=True, gates=GatePolicy(frozenset({1})))
    )

    # T1 reused (its result points at the original entry, not a fresh run)
    assert results["T1"].output == "done: a"
    # T2 ran on approve
    assert results["T2"].ok is True
    assert results["T2"].output.startswith("done: b")
    assert _result_body(ledger, "T2") is not None
    # no SECOND gate_pending was raised on resume (the guard matched the resolution)
    assert len(ledger.query(kind="gate_pending")) == 1
    assert ledger.query(kind="gate_stopped") == []
    assert ledger.verify(deep=True) is True


def test_edit_resume_rewrites_the_gated_task_instruction():
    ledger = make_ledger()
    _seed_run(ledger, "gate_edited", edits={"T2": "NEW"})
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))

    results = asyncio.run(
        dispatch_plan(plan, ledger, _EchoSaw(), resume=True, gates=GatePolicy(frozenset({1})))
    )

    # the witnessed T2 task carries the edited instruction, and the agent saw it
    t2_task = next(
        ledger.get_payload(e.payload_hash)
        for e in ledger.query(kind="task")
        if ledger.get_payload(e.payload_hash)["id"] == "T2"
    )
    assert t2_task["instruction"] == "NEW"
    assert results["T2"].output.startswith("NEW")  # ran on the replacement instruction
    assert len(ledger.query(kind="gate_pending")) == 1  # no duplicate pending
    assert ledger.verify(deep=True) is True
