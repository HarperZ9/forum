# Forum Tiered Chat Endpoints Design

## Purpose

Forum can now route task agents to cheap, capable, and frontier executors by
roster policy. The current tier wiring only accepts shell commands. That works,
but it forces local OpenAI-compatible servers such as Ollama, vLLM, LM Studio,
and llama.cpp behind adapter scripts or CLI wrappers.

This slice adds per-tier OpenAI-compatible chat endpoint flags so a local runtime
can map each roster tier directly to a server/model pair.

## Current State

`--chat-url` builds one `ChatExecutor` and uses it as the global/control
executor. `--cheap-cmd`, `--capable-cmd`, and `--frontier-cmd` build tier
`SubprocessExecutor`s and wrap them with `TieredExecutor`.

There is no way to say:

- cheap tasks use `http://localhost:11434/v1/chat/completions` with model
  `phi3`;
- capable tasks use the same server with model `llama3`;
- frontier tasks use a vLLM server with model `qwen2.5-coder`;
- control roles keep using the base executor.

## Design

Add per-tier chat flags to `submit`, `serve`, and `mcp` through the shared
`_add_executor` path:

- `--cheap-chat-url`, `--cheap-model`, `--cheap-api-key-env`;
- `--capable-chat-url`, `--capable-model`, `--capable-api-key-env`;
- `--frontier-chat-url`, `--frontier-model`, `--frontier-api-key-env`.

`_tier_executors(args)` will build each tier in this order:

1. If `<tier>_chat_url` is present, return `ChatExecutor(<tier>_model or tier,
   base_url=<tier>_chat_url, api_key_env=<tier>_api_key_env)`.
2. Else if `<tier>_cmd` is present, return `SubprocessExecutor`.
3. Else omit the tier.

The global executor priority is unchanged: global `--chat-url` beats `--api`,
which beats `--cmd`. If tier flags exist without a global executor, the default
control executor remains the first configured tier in `capable`, `frontier`,
`cheap` order, matching the existing tier-command behavior.

## Behavior

- Tier chat executors can be mixed with tier command executors.
- A tier chat executor wins over a tier command executor for the same tier.
- Missing per-tier model defaults to the tier name.
- Existing single-executor commands are unchanged.
- No real network is touched in tests; tests inspect constructed executor
  objects and existing `ChatExecutor` unit tests cover request behavior.

## Tests

Use TDD. Add tests before implementation for:

- tier chat flags constructing `TieredExecutor` with `ChatExecutor` per selected
  tier;
- tier chat flags defaulting a missing model to the tier name;
- tier chat flags taking precedence over tier command flags for the same tier;
- parser availability on `submit`, `serve`, and `mcp` through the shared helper.

## Documentation

Update README and architecture notes to document direct local endpoint mapping by
roster tier.

## Non-Goals

This does not add a config file, endpoint health checks, model downloads,
provider-specific request formats, streaming, embeddings, dynamic tier promotion,
or learned scheduler policy.
