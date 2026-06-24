"""Forum — a tour of the accountable core (v0.1).

Walks the primitives on a small example:
  route work to capability lanes -> plan a dependency DAG ->
  witness every step in a tamper-evident ledger -> verify, detect tamper, replay.

The "execution" here is a stub: a real executor (Claude Code subagent / API / CLI)
is a later milestone. The point of the demo is the *witnessing*, not the work.

Run:  python examples/demo.py        # zero dependencies, no install needed
"""

from __future__ import annotations

import pathlib
import sys

# Make `forum` importable straight from a checkout (src layout), no install needed.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.ledger import InMemoryStorage, Ledger
from forum.plan import Plan, Task
from forum.policy import Policy
from forum.roster import loads
from forum.routing import LexicalRouter

ROSTER_TOML = """
[[agent]]
name = "backend"
category = "engineering"
domain = "APIs, databases, server logic"
keywords = ["api", "database", "schema", "auth", "server", "endpoint"]
model_tier = "capable"
executor = "stub"

[[agent]]
name = "frontend"
category = "engineering"
domain = "UI, components, styling"
keywords = ["ui", "frontend", "react", "css", "component", "page"]
model_tier = "capable"
executor = "stub"

[[agent]]
name = "docs"
category = "support"
domain = "documentation and guides"
keywords = ["docs", "readme", "guide", "tutorial", "changelog"]
model_tier = "cheap"
executor = "stub"
"""


def rule(title: str) -> None:
    print("\n" + title)
    print("-" * len(title))


def main() -> None:
    roster = loads(ROSTER_TOML)
    router = LexicalRouter()
    ledger = Ledger(InMemoryStorage(), clock=_clock())
    policy = Policy(allowed_categories=frozenset({"engineering", "support"}), max_parallel=2)

    request = ledger.append(actor="client", kind="request", payload={"batch": "incoming work"})

    # 1. Route requests to capability lanes — deterministic, no model call.
    rule("1. Routing (deterministic Tier-0; decides a lane or escalates)")
    for text in [
        "build the database schema and the auth endpoint",
        "build the react component and css for the page",
        "write the readme docs and the guide",
        "summon a unicorn",
    ]:
        r = router.score(text, roster)
        verdict = r.decided or f"escalate -> needs an LLM classifier (confidence {r.confidence:.2f})"
        print(f"  {text!r:>50}  ->  {verdict}")
        ledger.append(
            actor="router",
            kind="route",
            payload={"task": text, "decided": r.decided, "confidence": r.confidence},
            causal_parent=request.seq,
        )

    # 2. Plan a multi-lane request as a dependency DAG, scheduled into waves.
    rule("2. Planning (DAG -> parallel waves, capped by policy max_parallel=2)")
    plan = Plan(
        (
            Task("T1", "backend", "design schema", ()),
            Task("T2", "backend", "build auth endpoint", ("T1",)),
            Task("T3", "frontend", "login page", ("T2",)),
            Task("T4", "docs", "write API docs", ("T2",)),
        )
    )
    waves = plan.schedule()
    for i, wave in enumerate(waves):
        for chunk in policy.cap_wave(wave):
            print(f"  wave {i}: {chunk}")

    # 3. "Execute" each task (stub) and witness every dispatch + result.
    rule("3. Witnessed execution (every step appended to the ledger)")
    plan_entry = ledger.append(actor="coordinator", kind="plan", payload={"waves": waves}, causal_parent=request.seq)
    last = plan_entry.seq
    for wave in waves:
        for tid in wave:
            task = next(t for t in plan.tasks if t.id == tid)
            assigned = ledger.append(
                actor="coordinator",
                kind="task",
                payload={"id": tid, "agent": task.agent, "instruction": task.instruction},
                causal_parent=plan_entry.seq,
            )
            output = _stub_execute(task)  # placeholder for a real executor
            last = ledger.append(
                actor=task.agent,
                kind="result",
                payload={"id": tid, "output": output},
                causal_parent=assigned.seq,
            ).seq
            print(f"  {tid} [{task.agent}] -> {output}")

    # 4. The point: the record is verifiable, not trusted.
    rule("4. Accountability: verify, tamper-detect, replay")
    print(f"  ledger entries        : {len(ledger.replay())}")
    print(f"  verify() (chain)      : {ledger.verify()}")
    print(f"  verify(deep=True)     : {ledger.verify(deep=True)}   (also re-checks payload bodies)")
    print(f"  Merkle checkpoint     : {ledger.checkpoint()[:16]}...")
    chain = ledger.causal_chain(last)
    print(f"  causal chain of last  : {' -> '.join(e.kind for e in chain)}")

    # Tamper with a stored payload body; watch deep-verify catch it.
    target = ledger.replay()[2]
    ledger._s._payloads[target.payload_hash] = {"task": "TAMPERED"}
    rule("   ...now tamper with a stored payload body (seq %d)" % target.seq)
    print(f"  verify() (chain only) : {ledger.verify()}   <- chain hashes still link")
    print(f"  verify(deep=True)     : {ledger.verify(deep=True)}  <- body tamper caught")


def _clock():
    ticks = iter(float(t) for t in range(1, 100_000))
    return lambda: next(ticks)


def _stub_execute(task: Task) -> str:
    return f"done: {task.instruction}"


if __name__ == "__main__":
    main()
