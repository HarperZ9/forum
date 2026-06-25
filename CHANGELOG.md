# Changelog

## 1.8.0: opt-in batched fsync

The durable ledger fsyncs every append, the strongest guarantee and the right default. For a high-throughput run where that per-append fsync is the bottleneck, this release adds an opt-in way to batch it, with the tradeoff stated plainly.

- **`FileStorage(dir, fsync_each=False)`**: appends are written and flushed to the OS (so they survive a process crash) but not fsynced per call, for throughput. Call `ledger.sync()` to fsync the logs at a point of your choosing (a phase boundary, the run's end). The default stays `fsync_each=True`: every append fsynced before it returns.
- **`Ledger.sync()` / `Storage.sync()`**: a new seam to force buffered writes down. A no-op for in-memory storage and for the default fsync-each mode; the durability control for batched mode. `build_orchestrator(..., fsync_each=False)` opts a daemon in.
- Honest tradeoff: a crash before `sync()` can lose the un-fsynced tail. The log stays append-only and the torn-trailing-line tolerance still applies, so what survives still verifies and replays exactly.

Pure standard library. 218 tests, plus 2 gated real-model tests. Run in `examples/run_batched_fsync.py`.

## 1.7.0: the verification seam

Forum already plans on context from an external brain (the ContextProvider seam, v1.1). This release adds its peer on the other end of the run: a seam for an external verifier to check the answer Forum produced, witnessed like everything else.

- **VerifierProvider**: a one-method seam (`verify(request, answer) -> Verification | None`). A peer flagship (the index brain), a proof-checker, or a test runner can implement it; Forum witnesses the verdict as a `verification` entry chained to the answer. The verdict carries `ok` (True verified, False refuted, None could-not-decide), a `detail`, and the verifier's `source`. The default `NullVerifier` abstains, so Forum stands alone, zero-dependency.
- **Witnessed, not blocking**: a refuted answer is recorded for the operator to see; what to do about it is policy, consistent with the rest of the engine. The summary and `forum bench` report verifications and refutations.
- This completes the provider pair: context flows in before the run, verification comes back after it, both witnessed, both clean seams to peer flagships that Forum never imports.

Pure standard library. 212 tests, plus 2 gated real-model tests. Run in `examples/run_verification.py`.

## 1.6.0: the DAG flows data (typed edges)

A plan is a DAG, but until now a dependency only meant "runs after." A downstream task could not see what it was building on. This release makes the edges carry data and gives them a type, so the plan expresses not just order but what flows.

- **Typed edges**: a dependency is a `data` edge by default (the downstream task receives the upstream's witnessed output) or an `order` edge (run-after, no data flow), declared as `{"id": "T1", "type": "order"}` in a plan or `Task(..., order_deps=frozenset({"T1"}))` in code. Both kinds constrain scheduling; only data edges carry output.
- **Witnessed data flow**: when a task runs, its data-upstream outputs are fed into its instruction, and the task entry records `data_from` (which upstreams it consumed). The plan entry records every edge with its type, so the typed DAG is in the record. The witnessed instruction stays the original; the injected prompt is reconstructable from the original plus the referenced upstream results. Escalation retries get the same upstream context, so a stronger model is not handicapped.
- API-compatible, with a deliberate behavior change: old plans and plain-string `depends_on` still construct, and because a plain id is a data edge, existing multi-task plans now feed upstream output into downstream instructions instead of dropping it. The witnessed instruction stays the original; only the executor sees the augmented prompt.

Pure standard library, deterministic. 205 tests, plus 2 gated real-model tests. Run in `examples/run_data_flow.py`.

## 1.5.0: the intent-judge, a grounded rung above the floor

v1.4 added a deterministic lexical floor that flags when a run's answer drifts from the request. A lexical signal has a known blind spot: a correct but paraphrased answer reuses few of the request's words and flags anyway. This release adds the rung that resolves those cases, on the same cheap-first ladder Forum already uses for routing and escalation.

- **Witnessed model intent-judge**: opt in with `Orchestrator(intent_judge=IntentJudge())` or `forum submit --judge-intent`. When, and only when, the lexical floor flags a run, a model reads the request and the answer, is told which request terms the floor found missing, and judges whether the answer truly drifted or merely paraphrased. The verdict (ok, score, reason) is witnessed as an `intent_judgment` entry chained to the flag it resolves, so it is auditable, not trusted. It runs through the run's executor and counts against the RunBudget, skipped once the budget is spent.
- **Cheap-first**: the free deterministic floor runs every time; the model judge fires only on a flag, so the common covered case spends nothing. A flagged-but-paraphrased answer is cleared (ok true); a genuinely off-target answer is judged off-target (ok false). The judge is one model's opinion, witnessed with its reasoning, not a confirmation.
- **In the summary and A/B**: `forum ledger summary` and `forum bench` now report judgments and confirmed drift, so you can measure real drift (the judge's verdict), not just lexical flags.

Pure standard library core; the judge is a model call behind the one executor seam. 195 tests, plus 2 gated real-model tests. Run in `examples/run_intent_judge.py`.

## 1.4.0: did the run answer the question?

Forum validates each task against its own instruction, but a run can pass every task and still drift from the original request. This release witnesses that gap. After a run synthesizes its answer, Forum records how much of the request the answer actually reflects, a reproducible signal you can read, compare, and act on.

- **Witnessed intent check**: a completed `submit()` appends an `intent_check` entry, chained to the answer, with a deterministic coverage score (the fraction of the request's content words the answer carries), the terms it missed, and whether that falls below a configurable threshold (`Orchestrator(intent_threshold=...)`). It is a lexical floor, not a semantic verdict: low coverage flags a run for a closer look, it does not block the run or declare the answer wrong. A grounded model intent-judge is the next rung above this floor.
- **In the summary and A/B**: `forum ledger summary` and `forum bench` now report intent checks and how many were flagged, so a prompt or model change that makes runs drift more or less is measured from the record, not guessed at.

Pure standard library, deterministic and reproducible. 186 tests, plus 2 gated real-model tests. Intent run in `examples/run_intent.py`.

## 1.3.0: reading the record

A witnessed run is only worth as much as what you can learn from it. This release turns the raw ledger into something you can read at a glance and compare across runs, while trusting nothing but the record itself. It is what lets the project measure its own improvement instead of asserting it.

- **Run summary**: `forum.report.summarize(ledger)` aggregates a witnessed run into counts (requests, plans, tasks, task results and failures, verdict pass and fail, escalations, budget stops, contexts, answers), model calls per model, the Merkle checkpoint, and the verify result. It reads only what was witnessed, so the summary is exactly as trustworthy as the ledger beneath it. On the CLI: `forum ledger summary [--json]`.
- **Ledger A/B**: `forum.report.compare(a, b)` reports the delta between two summaries, and `forum bench A B [--json]` compares two ledgers side by side. This is how you prove a change actually helped: fewer model calls, fewer failures, fewer escalations, read from the record rather than claimed.

170 tests, plus 2 gated real-model tests. Summary and A/B run in `examples/run_summary.py`.

## 1.2.0: witnessed model-tier escalation

Research-informed (arXiv 2026-06): FairTutor's selective escalation cut cost 71.6% at near-premium quality; "Forced Deferral" showed confidence-based cascades are adversarially gameable; "Reliability without Validity" showed single LLM judges are biased. So Forum escalates on a verifiable, witnessed signal, not opaque model confidence.

- **Model identity in the ledger**: every result records the `model` that produced it (the executor's `model_id`, else its type), so a run is reproducible and silent model or provider drift becomes visible.
- **Witnessed tier-escalation**: give the Orchestrator an ordered ladder of stronger executors (`escalation_executors=[...]`). When a task's witnessed verdict fails, Forum retries it up the ladder, witnessing a `tier_escalation` entry plus a fresh result and verdict, and uses the first passing result. Bounded by the same RunBudget. The trigger is the auditable verdict, not model confidence.

160 tests, plus 2 gated real-model tests. Escalation run in `examples/run_escalation.py`.

## 1.1.0: the witnessed run contract

Research-informed (the agent-loops, second-brain, and model-testing videos): bound the run, and route on organized context.

- **ContextProvider seam**: `submit()` pulls organized context from a `ContextProvider` (the clean seam to a "brain" like the index flagship) before planning, feeds it into the plan, and witnesses the exact context that shaped it (`request -> context -> plan`). The default `NullContextProvider` keeps Forum standing alone, zero-dependency.
- **RunBudget**: `submit(request, budget=RunBudget(max_model_calls=..., max_seconds=...))` bounds a run. When the budget is spent the run stops gracefully, witnesses a `budget` entry, and stays fully verifiable. On the CLI: `forum submit ... --max-model-calls N --max-seconds S`.
- Pure standard library, witnessed by design. Remaining research-derived ideas (witnessed model-tier escalation, typed DAG edges, run summaries, drift checks) are on the roadmap.

156 tests, plus 2 gated real-model tests. Contract run in `examples/run_contract.py`.

## 1.0.0: the engine is complete

Forum is a complete, accountable orchestration engine: durable, verifiable, daemonized, installable, and documented.

- The full stack is here and tested: the witnessed causal ledger (verify, deep-verify, replay, causal chains, Merkle checkpoints), durable file-backed storage, deterministic routing with a model-backed classifier on escalation, the DAG planner and bounded-concurrency dispatcher, the control loop (coordinate, validate, synthesize), model-agnostic executors (any command, any OpenAI-compatible endpoint including local servers that need no account, and the Anthropic API), an HTTP daemon and an MCP surface over one long-lived ledger, and a `forum` CLI.
- A built-in roster of 24 plain capability lanes ships in the box.
- Quality gates in CI: ruff, mypy, and coverage. 144 tests, plus 2 gated real-model tests.
- Docs: README, ARCHITECTURE, RUNNING, SECURITY, RELEASING.

Pure standard library, zero third-party runtime dependencies. Fair-source.

## 0.10.0: harden and prove

The accountability gets sharper and the routing ladder is complete.

- **Witnessing-hardening**: each `verdict` now causal-parents the specific `result` entry it judged, so `causal_chain(verdict)` reconstructs the full path (request to plan to task to result to verdict). Control roles get role-specific ids (`control:coordinator` and so on) instead of a shared sentinel. `ApiExecutor` reports an unexpected response shape clearly. Empty-plan submit is covered.
- **The routing ladder is wired**: `Orchestrator.assign` does Tier-0 lexical routing and escalates to the Tier-2 Classifier when keywords cannot decide, witnessing the route and any classification. `submit_one` runs a single task end to end through that ladder.
- **Real-model proof**: a gated integration test (`tests/test_real_model.py`, skipped unless `FORUM_RUN_REAL=1` and `ANTHROPIC_API_KEY` are set) runs a full `submit` and `submit_one` against a live model and asserts the ledger stays deep-verifiable. See `RUNNING.md`.

143 tests, plus 2 gated real-model tests skipped by default.

## 0.9.0: a command line

Forum is something you run now, not just import.

- **`forum` CLI**: a console entry point. `forum route "..."` (no model needed), `forum submit "..." --api|--cmd` (witnessed), `forum serve` (HTTP daemon), `forum mcp` (MCP stdio server), and `forum ledger verify | show | replay <seq> | get <seq>` to inspect the record.
- Executor selection by flag: `--api` (Anthropic API, reads `ANTHROPIC_API_KEY`) or `--cmd "<model cli>"` (any command, run once per task). Routing and the ledger commands need no model.
- Pure stdlib `argparse`; no new dependencies.

135 tests.

## 0.8.0: the MCP surface

The lone optional edge: Forum speaks MCP now.

- **MCP surface**: an MCP (JSON-RPC 2.0 over stdio) server, `forum.mcp_surface`, exposing `submit`, `route`, `plan`, `status`, `verify`, and `ledger_get` as tools. Serve it with `python -m forum.mcp_surface`.
- It is a thin adapter over the HTTP surface: each tool maps to an HTTP method and path and is served by the same `HttpSurface`, so the MCP and HTTP surfaces cannot drift. A tool-layer failure reports via `isError`; a protocol error uses a JSON-RPC error code.
- The `handle()` and `process_line()` seams are sockets-free and unit-tested directly; `serve_stdio()` wires real streams.

121 tests. MCP run in `examples/run_mcp.py`.

## 0.7.0: the daemon (HTTP)

Forum runs as an always-on service now.

- **HTTP daemon**: a stdlib-asyncio HTTP/1.1 server (no web framework), `forum.daemon.Daemon`, serving `GET /health`, `GET /status`, `GET /verify`, `GET /checkpoint`, `GET /ledger/{seq}`, `GET /replay/{seq}`, `POST /route`, `POST /plan`, and `POST /submit`. One daemon owns one long-lived, durable (`FileStorage`) ledger, so every request witnesses into the same verifiable record.
- **HttpSurface**: the request-to-Orchestrator mapping is a sockets-free coroutine, so every endpoint and error path is unit-tested directly.
- **Lifecycle**: start, stop, graceful drain, ephemeral-port binding; `build_orchestrator(dir)` wires the durable ledger and the default roster. `/submit` and `/plan` need a model executor and return a clear 502 under the default EchoExecutor.
- A new `Ledger.get(seq)` accessor backs the ledger endpoint.

100 tests. Daemon run in `examples/run_daemon.py`.

## 0.6.0: a roster in the box

A fresh install has a real roster now, not just an example in the demo.

- **Default roster**: 24 domain-neutral capability lanes (engineering, graphics, support, research) shipped as `manifests/default-roster.toml` inside the package, loaded with `roster.load_default()`. Plain capability names, no personas.
- Every lane is keyword-routable: a request built from a lane's keywords routes to that lane, verified across all 24.
- The manifest ships as package data, so `load_default()` works from a source checkout and from an installed wheel.

76 tests.

## 0.5.0: a durable ledger

The ledger can outlive the process now.

- **FileStorage**: a durable, file-backed implementation of the `Storage` protocol, two append-only JSONL logs (entries and content-addressed payloads) in a directory. A fresh `FileStorage` over the same directory recovers the exact ledger after a restart, with `verify`, `replay`, `causal_chain`, and the Merkle `checkpoint` all intact.
- **Crash-tolerant, tamper-honest**: a single torn trailing line (an append a crash cut short) is dropped on load; interior corruption raises a typed `StorageCorruption`; a tampered (reordered) file still loads so `verify()` can report it false. Every append is flushed and fsynced before it is mirrored to memory.
- Still pure standard library, still zero runtime dependencies. The core stays storage-agnostic: `FileStorage` is an edge adapter behind the existing protocol.

70 tests. Durable run in `examples/run_durable.py`.

## 0.4.0: the control loop

Forum plans a plain request on its own now.

- **Coordinator**: turns a plain request into a validated task plan, using a model.
- **Classifier**: picks an agent for a task when keyword routing cannot decide.
- **Validator**: judges a result against its instruction. A task that fails is witnessed as not ok, not blessed by the judge.
- **Synthesizer**: combines the results into one answer.
- **`Orchestrator.submit(request)`**: runs the whole loop, request to answer, every step witnessed and deep-verifiable.
- **`ask_json`**: a small helper that parses structured output from a model reply, tolerant of prose wrapping, with brace-safe prompt building.

59 tests. Full loop in `examples/run_request.py`.

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
