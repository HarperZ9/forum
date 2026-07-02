import asyncio

from forum.dispatch import dispatch_plan
from forum.executor import Result
from forum.gates import GatePolicy
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task


def make_ledger():
    ticks = iter(float(t) for t in range(1, 1000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


class _CountingExecutor:
    """Echoes; counts how many times each task id was actually run."""

    def __init__(self):
        self.calls: dict[str, int] = {}

    async def run(self, assignment):
        self.calls[assignment.task_id] = self.calls.get(assignment.task_id, 0) + 1
        return Result(assignment.task_id, assignment.agent, f"done: {assignment.instruction}")


def _seed_run_with_rejection(led):
    """Pre-seed a run: plan, a witnessed T1 ok result, a gate_pending + gate_rejected for wave 1."""
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
    led.append(
        actor="operator", kind="gate_rejected",
        payload={"run_seq": plan.seq, "wave": 1, "approver": "op", "reason": "unsafe"},
        causal_parent=pend.seq,
    )
    return plan.seq


def test_reject_halts_the_gated_wave():
    """CAN-IT-FAIL: a rejected gate must NOT run the gated work (T2).

    Pre-seed plan + T1 ok result + gate_rejected{wave:1}, then resume. The gated
    wave's executor must never be called for T2, no result entry appears for T2,
    and a gate_stopped chained to the rejection distinguishes halt from completion.
    """
    ledger = make_ledger()
    run_seq = _seed_run_with_rejection(ledger)
    plan = Plan((Task("T1", "x", "a", ()), Task("T2", "x", "b", ("T1",))))
    executor = _CountingExecutor()

    results = asyncio.run(
        dispatch_plan(plan, ledger, executor, resume=True, gates=GatePolicy(frozenset({1})))
    )

    # (a) a gate_stopped chained to the rejection exists
    rejection = ledger.query(kind="gate_rejected")[0]
    stops = [e for e in ledger.query(kind="gate_stopped")]
    assert len(stops) == 1
    assert stops[0].causal_parent == rejection.seq
    stop_body = ledger.get_payload(stops[0].payload_hash)
    assert stop_body["run_seq"] == run_seq and stop_body["wave"] == 1

    # (b) NO result entry for T2
    result_ids = [ledger.get_payload(e.payload_hash).get("id") for e in ledger.query(kind="result")]
    assert "T1" in result_ids
    assert "T2" not in result_ids

    # (c) the executor was never called for T2 (T1 was reused, not run)
    assert executor.calls.get("T2", 0) == 0

    # T2 is absent from the returned results, and the chain still verifies
    assert "T2" not in results
    assert ledger.verify(deep=True) is True
