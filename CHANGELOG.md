# Changelog

## 0.3.0: real executors

Forum does real work now, not just toy plans.

- **SubprocessExecutor**: runs an external command per task via `asyncio.create_subprocess_exec` (no shell, so no injection surface). Point it at any CLI, including a model CLI such as `["claude", "-p"]`.
- **ApiExecutor**: drives a model via the Anthropic Messages API over stdlib `urllib`, with the blocking call kept off the event loop and an injectable opener for tests.
- **Failure policy**: a task whose executor raises is witnessed as `ok=False` and the rest of the wave still runs. The ledger stays deep-verifiable.

46 tests. Real run in `examples/run_real.py`.

## 0.2.0: the runtime

The engine runs. A plan now executes end to end, with every step witnessed.

- **Executor**: an `Executor` protocol and a deterministic `EchoExecutor` stand-in, the single async seam where a real model-driven executor will drop in.
- **Actor and Supervisor**: a minimal async mailbox actor (observable let-it-crash) and a restart supervisor.
- **Dispatcher**: `dispatch_plan` schedules a plan into waves and runs each task through the executor, bounded by a semaphore under `asyncio.TaskGroup`, appending plan, task, and result entries to the ledger with causal links. Independent tasks run concurrently and the run stays deep-verifiable.
- **Orchestrator**: ties routing, planning, and witnessed dispatch into `submit_plan`.

39 tests. End-to-end run in `examples/run.py`.

## 0.1.0: core foundation

The accountable core, pure standard library, zero runtime dependencies.

- **Ledger**: append-only hash chain with a content-addressed payload store:
  `verify()` (chain integrity), `verify(deep=True)` (re-checks payload bodies,
  tolerates redacted/hash-only), `replay()`, `query()`, `causal_chain()`, and a
  domain-separated Merkle `checkpoint()` that resists the CVE-2012-2459 odd-node
  second-preimage collision. Fail-fast on out-of-range lookups; cycle-guarded
  causal walks.
- **Routing**: deterministic, specificity-aware `LexicalRouter` (Tier-0): decides a
  lane or escalates with a confidence score; total-ordered, roster-order-independent.
- **Roster**: validated TOML capability-manifest loader (rejects non-list keywords,
  unknown tiers, missing fields).
- **Plan**: DAG scheduler into ordered parallel waves; cycle and unknown-dependency
  detection.
- **Policy**: category scope gate and parallel-wave capping.

29 tests. Runnable tour in `examples/demo.py`.
