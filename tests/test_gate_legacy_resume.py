"""A run paused under 1.14.0 resumes under 1.15.0 with the approval it was given.

1.14.0 keyed every gate in a ledger to the first plan entry's seq and wrote plan
entries without a digest. A resume of such a run must find that key again, even
when 1.14.0 had already resumed it once (a second plan entry), and a plan whose
waves differ must still start a run of its own.
"""
import asyncio

from forum.dispatch import dispatch_plan
from forum.executor import EchoExecutor
from forum.gates import GatePolicy
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task

GATES = GatePolicy(frozenset({1}))
WAVES = [["T1"], ["T2"]]
EDGES = [{"from": "T1", "to": "T2", "type": "data"}]


def _ledger():
    ticks = iter(float(t) for t in range(1, 10_000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _seed_1_14_run(led, *, resumed_once):
    """What 1.14.0 wrote: a digest-free plan, T1 done, a gate keyed to the first plan."""
    req = led.append(actor="client", kind="request", payload={"tasks": ["T1", "T2"]})
    first = led.append(actor="dispatch", kind="plan", payload={"waves": WAVES, "edges": EDGES},
                       causal_parent=req.seq)
    task = led.append(actor="dispatch", kind="task",
                      payload={"id": "T1", "agent": "x", "instruction": "draft", "data_from": []},
                      causal_parent=first.seq)
    led.append(actor="x", kind="result",
               payload={"id": "T1", "output": "done: draft", "ok": True, "model": "EchoExecutor"},
               causal_parent=task.seq)
    pend = led.append(actor="dispatch", kind="gate_pending",
                      payload={"run_seq": first.seq, "wave": 1, "tasks": ["T2"], "question": "q",
                               "requested_by": "dispatch"}, causal_parent=first.seq)
    if resumed_once:  # a 1.14.0 resume before the person decided: another plan entry
        led.append(actor="dispatch", kind="plan", payload={"waves": WAVES, "edges": EDGES})
    led.append(actor="operator", kind="gate_approved",
               payload={"run_seq": first.seq, "wave": 1, "approver": "person", "note": ""},
               causal_parent=pend.seq)


def _plan():
    return Plan((Task("T1", "x", "draft", ()), Task("T2", "x", "publish", ("T1",))))


def test_a_run_paused_under_1_14_resumes_with_its_approval():
    led = _ledger()
    _seed_1_14_run(led, resumed_once=False)
    results = asyncio.run(dispatch_plan(_plan(), led, EchoExecutor(), resume=True, gates=GATES))
    assert results["T2"].ok is True
    assert len(led.query(kind="gate_pending")) == 1


def test_a_run_resumed_once_under_1_14_still_finds_its_gate():
    led = _ledger()
    _seed_1_14_run(led, resumed_once=True)
    results = asyncio.run(dispatch_plan(_plan(), led, EchoExecutor(), resume=True, gates=GATES))
    assert results["T2"].ok is True
    assert len(led.query(kind="gate_pending")) == 1


def test_a_plan_with_other_waves_does_not_continue_a_1_14_run():
    led = _ledger()
    _seed_1_14_run(led, resumed_once=True)
    other = Plan((Task("T1", "x", "draft", ()), Task("T2", "x", "publish", ("T1",)),
                  Task("T3", "x", "announce", ("T1",))))
    results = asyncio.run(dispatch_plan(other, led, EchoExecutor(), resume=True, gates=GATES))
    assert "T2" not in results and "T3" not in results
    assert len(led.query(kind="gate_pending")) == 2
