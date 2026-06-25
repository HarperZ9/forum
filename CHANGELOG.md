# Changelog

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
