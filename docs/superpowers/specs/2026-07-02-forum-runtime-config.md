# Forum Runtime Config Spec

Date: 2026-07-02

## Problem

Forum can now route assignments to cheap, capable, and frontier model tiers,
but the operator must repeat endpoint and command flags for every `submit`,
`serve`, or `mcp` invocation. That is too brittle for a platform execution
layer. The runtime policy needs a durable local shape that can describe local
models, commands, and tier preferences without committing credentials.

## Goals

- Add a local TOML runtime config file accepted by `submit`, `serve`, and `mcp`.
- Support a default executor and per-tier executors for `cheap`, `capable`, and
  `frontier`.
- Support OpenAI-compatible chat endpoints and command executors in config.
- Keep secrets out of the file by accepting only `api_key_env` names, not API
  key values.
- Let explicit CLI flags override the config for the same default or tier.
- Keep the existing flag-only behavior unchanged.

## Non-Goals

- No new model provider dependency.
- No automatic config discovery in this slice.
- No generated config wizard yet.
- No persistent mutation of config files.

## Config Shape

```toml
[runtime.default]
chat_url = "http://localhost:11434/v1/chat/completions"
model = "llama3"
api_key_env = "LOCAL_MODEL_KEY"

[runtime.tiers.cheap]
chat_url = "http://localhost:11434/v1/chat/completions"
model = "phi3"

[runtime.tiers.capable]
cmd = "ollama run llama3"

[runtime.tiers.frontier]
chat_url = "http://localhost:8000/v1/chat/completions"
model = "qwen2.5-coder"
```

Each executor table accepts either:

- `chat_url`, optional `model`, optional `api_key_env`
- `cmd`

If both `chat_url` and `cmd` are present, `chat_url` wins to match existing CLI
tier precedence.

## Validation

- The top-level `runtime` section must be a table when present.
- `runtime.default` and each `runtime.tiers.<tier>` entry must be tables.
- Tier names are restricted to `cheap`, `capable`, and `frontier`.
- `chat_url`, `model`, `api_key_env`, and `cmd` must be strings when present.
- Missing or malformed files fail fast with a readable `ValueError`.

## Precedence

1. Load config default and tier executors from `--runtime-config`.
2. Overlay explicit global executor flags (`--chat-url`, `--api`, `--cmd`) on
   top of the config default.
3. Overlay explicit tier flags on top of matching config tiers.
4. Build a `TieredExecutor` when any tier executor exists.
5. If no default executor exists, choose the first configured tier in the
   existing capable, frontier, cheap order.

## Acceptance Criteria

- Runtime config can build default and tier chat executors.
- Runtime config can build command executors while preserving Windows paths.
- Explicit CLI tier flags override config tier entries.
- `--runtime-config` is available for `submit`, `serve`, and `mcp`.
- Invalid tier names raise a clear `ValueError`.
- Existing CLI executor tests continue to pass.
