# Forum Runtime Config Plan

Date: 2026-07-02

## Scope

Add persistent local runtime config support for tiered model routing while
preserving the existing CLI-only executor path.

## Steps

1. Add failing tests.
   - Unit tests for parsing TOML runtime config into default and tier executors.
   - Unit tests for invalid tier validation.
   - CLI tests for `--runtime-config` parsing and override precedence.
2. Add `src/forum/runtime_config.py`.
   - Read TOML using `tomllib`.
   - Convert executor specs into `ChatExecutor` or `SubprocessExecutor`.
   - Return `(default_executor, tier_executors)` so CLI can overlay flags.
3. Integrate CLI.
   - Add `--runtime-config` in `_add_executor`.
   - Load config first in `_make_executor`.
   - Overlay explicit base and tier flags.
   - Wrap `submit`, `serve`, and `mcp` runtime config errors as exit code `2`.
4. Document.
   - Add README examples for config use.
   - Update architecture notes for persistent runtime policy.
5. Verify.
   - Run targeted tests for runtime config and CLI.
   - Run full test suite if targeted tests pass.
   - Inspect diff and run staged whitespace/secret checks before commit.

## Risks

- `shlex.split` semantics differ on Windows; use the same `posix=os.name != "nt"`
  rule as existing CLI command parsing.
- Broad secret scans may flag `api_key_env` option names. Treat those as false
  positives only after inspecting the exact lines.
- `src/forum/cli.py` is already larger than the project guideline. Keep new CLI
  code minimal and move parsing/building logic to a dedicated module.
