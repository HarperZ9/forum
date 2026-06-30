# Forum Agent Instructions

## Scope

Forum is the Project Telos agent orchestration and causal ledger tool. Changes
should improve routing, execution, replay, human-readable prose, ledger joins,
or model-agnostic host integration.

## Developer Contract

- Keep CLI, HTTP, MCP, and Python package surfaces aligned.
- Preserve ledger joins between request, route, execution, validation, and
  final answer.
- Keep humanization features evidence-preserving: improve readability without
  dropping claims, caveats, or receipts.
- Keep README, `USAGE.md`, `CHANGELOG.md`, and examples current when workflows
  change.

## Verification

Run the targeted slice for the touched surface first:

```bash
python -m pip install -e ".[dev]"
python -m pytest
forum status --json
forum doctor --json
```

For delivery-surface changes, also run:

```bash
python -m public_surface_sweeper . --workspace --json
```
