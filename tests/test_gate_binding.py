"""An approval covers one run, the exact content that gate showed, and no more.

Falsifiers for review findings F1 and F2. Each test failed on forum-engine 1.14.0
and on the first 1.15.0 candidate: a resume continued "the latest plan in the
ledger", so approving one run opened another run's gate, an approved run could
not resume once a later run had started, a resume with a different or rewritten
plan ran under the old approval, and an edit at one gate rewrote a later wave.
"""
import asyncio
import inspect

import pytest

from forum.dispatch import dispatch_plan
from forum.executor import EchoExecutor
from forum.gates import GatePolicy, resolve_gate
from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task

G = GatePolicy(frozenset({0}))
# Written against APIs present in 1.14.0 too, so each failure there shows the defect.
_STRICT = {"require_pending": True} if "require_pending" in inspect.signature(
    resolve_gate).parameters else {}


def _ledger():
    ticks = iter(float(t) for t in range(1, 100_000))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def _approve(led, run_seq, wave, kind="gate_approved", **kw):
    return resolve_gate(led, run_seq, wave, kind, approver="person", **_STRICT, **kw)


def _pending(led):
    out = []
    for e in led.query(kind="gate_pending"):
        body = led.get_payload(e.payload_hash)
        out.append((body["run_seq"], body["wave"]))
    return out


def _outputs(led):
    return {led.get_payload(e.payload_hash)["id"]: led.get_payload(e.payload_hash)["output"]
            for e in led.query(kind="result")}


def _plan(*pairs):
    return Plan(tuple(Task(tid, "x", text, ()) for tid, text in pairs))


def _run(plan, led, gates=G, **kw):
    return asyncio.run(dispatch_plan(plan, led, EchoExecutor(), gates=gates, **kw))


def test_approving_one_run_does_not_open_another_runs_gate():
    led = _ledger()
    plan_a = _plan(("A1", "rotate the signing key"))
    _run(plan_a, led)
    _run(_plan(("B1", "read the changelog")), led)
    keys = _pending(led)
    assert len(keys) == 2, "each fresh run raises its own gate"
    _approve(led, keys[1][0], 0)  # the person approves run B only
    _run(plan_a, led, resume=True)  # then resumes run A
    assert "A1" not in _outputs(led)
    assert led.verify(deep=True) is True


def test_an_approved_run_still_resumes_after_a_later_run_started():
    led = _ledger()
    plan_a = _plan(("A1", "rotate the signing key"))
    _run(plan_a, led)
    _run(_plan(("B1", "read the changelog")), led)
    keys = _pending(led)
    assert len(keys) == 2, "each fresh run raises its own gate"
    _approve(led, keys[0][0], 0)  # the person approves run A
    _run(plan_a, led, resume=True)
    assert _outputs(led).get("A1") == "done: rotate the signing key"
    assert len(_pending(led)) == 2, "the resume found run A's gate and raised no new one"


def test_a_resume_with_a_different_plan_needs_its_own_approval():
    led = _ledger()
    _run(_plan(("T1", "list files")), led)
    (run_seq, _), = _pending(led)
    _approve(led, run_seq, 0)
    _run(_plan(("X9", "empty the release bucket")), led, resume=True)
    assert "X9" not in _outputs(led)
    assert len(_pending(led)) == 2, "the different plan raised a gate of its own"


def test_an_approval_does_not_cover_a_rewritten_instruction():
    led = _ledger()
    _run(_plan(("T1", "read the changelog")), led)
    (run_seq, _), = _pending(led)
    _approve(led, run_seq, 0)
    _run(_plan(("T1", "delete the changelog")), led, resume=True)
    assert "delete" not in _outputs(led).get("T1", "")


def test_an_approval_does_not_cover_a_changed_agent_or_done_criteria():
    led = _ledger()
    _run(Plan((Task("T1", "reader", "summarize the notes", ()),)), led)
    (run_seq, _), = _pending(led)
    _approve(led, run_seq, 0)
    _run(Plan((Task("T1", "deployer", "summarize the notes", ()),)), led, resume=True)
    _run(Plan((Task("T1", "reader", "summarize the notes", (), done_when=("push to main",)),)),
         led, resume=True)
    assert "T1" not in _outputs(led)


def test_the_gate_shows_the_instructions_it_approves():
    led = _ledger()
    gates = GatePolicy(frozenset({1}))
    plan = Plan((Task("T1", "x", "draft notes", ()),
                 Task("T2", "x", "summarize notes", ("T1",), done_when=("under 100 words",))))
    _run(plan, led, gates=gates)
    body = led.get_payload(led.query(kind="gate_pending")[0].payload_hash)
    assert body["tasks"] == ["T2"]
    assert body["instructions"] == {"T2": "summarize notes\n\nDone criteria:\n- under 100 words"}
    assert isinstance(body.get("wave_digest"), str) and len(body["wave_digest"]) == 64


def test_an_edit_at_one_gate_is_refused_for_a_task_of_another_wave():
    led = _ledger()
    gates = GatePolicy(frozenset({0, 1}))
    plan = Plan((Task("T1", "x", "draft notes", ()), Task("T2", "x", "summarize notes", ("T1",))))
    _run(plan, led, gates=gates)
    (run_seq, _), = _pending(led)
    with pytest.raises(ValueError) as refused:
        _approve(led, run_seq, 0, "gate_edited", edits={"T2": "INJECTED"})
    assert getattr(refused.value, "code", None) == "INVALID_ARGUMENT"
    assert led.query(kind="gate_edited") == [], "a refused edit writes nothing"


def test_an_edit_chained_to_one_gate_never_rewrites_a_later_wave():
    # The library path that skips validation: an edit entry chained to the wave 0
    # gate names a wave 1 task. Dispatch applies an edit only to its own wave.
    led = _ledger()
    gates = GatePolicy(frozenset({0, 1}))
    plan = Plan((Task("T1", "x", "draft notes", ()), Task("T2", "x", "summarize notes", ("T1",))))
    _run(plan, led, gates=gates)
    (run_seq, _), = _pending(led)
    pend = led.query(kind="gate_pending")[0]
    led.append(actor="operator", kind="gate_edited",
               payload={"run_seq": run_seq, "wave": 0, "approver": "person",
                        "edits": {"T1": "draft notes", "T2": "INJECTED"}, "note": ""},
               causal_parent=pend.seq)
    _run(plan, led, gates=gates, resume=True)
    later = [k for k in _pending(led) if k[1] == 1]
    assert later, "wave 1 raises its own gate"
    _approve(led, later[0][0], 1)
    _run(plan, led, gates=gates, resume=True)
    assert "INJECTED" not in _outputs(led).get("T2", "")
    assert _outputs(led).get("T2", "").startswith("done: summarize notes")
