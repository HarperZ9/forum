# Contributing

Forum's core is pure standard library, and the goal is to keep it that way, with no
third-party runtime dependencies. Contributions that hold that line are welcome.

## Setup

```bash
pip install -e ".[dev]"
pytest
```

## Ground rules

- **Zero runtime dependencies.** `pytest` is the only dev dependency. If a change
  needs a third-party package at runtime, it belongs in an edge adapter, not the core.
- **Small, focused modules.** One clear responsibility per file.
- **Plain capability names.** Name things after what they do (`ledger`, `routing`),
  not metaphors or personas.
- **Deterministic tests.** Inject clocks; never rely on the wall clock or randomness
  in an assertion.
- **Behavior comes with a test.** Every new behavior ships with a test that asserts
  it. The suite is the contract.

## Pull requests

Keep them scoped to one change. Describe what it does and why, and make sure
`pytest` and `python examples/demo.py` both pass.
