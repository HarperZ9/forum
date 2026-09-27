"""Which run a resumed plan continues, and what content a gate covers.

A gate decision answers one question about one run: may this wave, with these
exact tasks, run? So the key a gate is filed under names the run, and the gate
records a digest of the wave it shows. Both are pure functions of the plan.

- ``plan_digest`` covers every task (id, agent, instruction, dependencies, done
  criteria). A resume continues the latest run whose plan entry carries the same
  digest, so a different or rewritten plan starts a run of its own.
- ``wave_digest`` covers the tasks of one wave; a gate counts a decision only when
  the gate it resolves showed this same content.

A plan entry written before 1.15.0 carries no digest. A resume still continues
it when its waves hold the same task ids, and its gates bind by task ids, the
only content those entries recorded.
"""
from __future__ import annotations

from forum.hashing import canonical_hash
from forum.ledger import Ledger
from forum.plan import Plan, Task


def _task_record(task: Task) -> dict[str, object]:
    return {
        "id": task.id,
        "agent": task.agent,
        "instruction": task.instruction,
        "depends_on": list(task.depends_on),
        "order_deps": sorted(task.order_deps),
        "done_when": list(task.done_when),
    }


def plan_digest(plan: Plan) -> str:
    """SHA-256 over every task of the plan, independent of task order."""
    return canonical_hash(sorted((_task_record(t) for t in plan.tasks), key=lambda r: str(r["id"])))


def wave_digest(tasks: list[Task]) -> str:
    """SHA-256 over the tasks of one wave, in id order."""
    return canonical_hash([_task_record(t) for t in sorted(tasks, key=lambda t: t.id)])


def wave_instructions(tasks: list[Task]) -> dict[str, str]:
    """What the person approves: each task's instruction with its done criteria."""
    return {t.id: t.contract_instruction() for t in sorted(tasks, key=lambda t: t.id)}


def resume_lineage(ledger: Ledger, digest: str, waves: list[list[str]]) -> int | None:
    """The run key a resume of this plan continues, or None to start a fresh run.

    The latest plan entry with the same ``plan_digest`` wins. With none, the latest
    plan entry written before digests existed wins when its waves match.
    The key is the entry's recorded ``run_seq`` (it was itself a resume) or its seq.
    """
    legacy: int | None = None
    for entry in reversed(ledger.query(kind="plan")):
        body = ledger.get_payload(entry.payload_hash)
        if not isinstance(body, dict):
            continue
        recorded = body.get("run_seq")
        key = recorded if type(recorded) is int else entry.seq
        if "plan_digest" in body:
            if body["plan_digest"] == digest:
                return key
        elif legacy is None and body.get("waves") == waves:
            legacy = key
    return legacy
