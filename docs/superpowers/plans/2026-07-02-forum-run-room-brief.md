# Forum Run-Room Brief Plan

Date: 2026-07-02

## Scope

Add a deterministic operator brief to the existing run-room read model and expose
it through the existing CLI room command.

## Steps

1. Add failing tests.
   - Extend `tests/test_run_room.py` for complete and action-required brief
     states.
   - Add a CLI test for `forum ledger room --brief`.
2. Implement brief generation in `src/forum/run_room.py`.
   - Add `BRIEF_SCHEMA`.
   - Compute `next_actions` once, then attach `brief`.
   - Add helpers for state, task counts, risk sentence, title, next step, and
     text rendering.
3. Integrate CLI.
   - Add `--brief` to `forum ledger room`.
   - Print `room_brief_text(room)` when requested.
4. Document.
   - Update README command examples and run-room module description.
   - Update architecture run-room section.
5. Verify and commit.
   - Run targeted run-room/CLI tests.
   - Run Ruff on changed Python files.
   - Run full pytest suite.
   - Stage and run whitespace/secret checks before committing.

## Risk Controls

- The brief must not invent facts; every sentence derives from the room payload.
- Existing `room_text` remains stable for users who rely on terse diagnostic
  output.
- HTTP and MCP do not need extra routing because the run-room JSON carries the
  new brief object.
