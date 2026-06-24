# Forum: CLAUDE.md

Guidance for AI coding agents working in this repository.

## Core constraints

- **Pure zero-dependency core.** Standard library only at runtime. `pytest` is the
  sole dev dependency. Anything that touches the outside world is an edge adapter.
- **Clean-room codebase.** No lineage to, or imports from, any internal or private
  project.
- **Plain capability names.** Name modules and functions after what they do
  (`hashing`, `ledger`, `routing`), not metaphors or personas.
- **Determinism.** Inject clocks; never rely on the wall clock or randomness in a way
  that affects output or an assertion.
- **Tests are the contract.** Every new behavior ships with a test that asserts it.

## Layout

- `src/forum/`: the pure core (hashing, message, ledger, roster, routing, plan, policy).
- `tests/`: one test module per source module.
- `examples/demo.py`: a runnable tour of the primitives.

## Working here

Run `pytest` and `python examples/demo.py` before proposing a change. Keep files
focused; if one grows beyond a single responsibility, split it.
