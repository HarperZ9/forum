# Running Forum for real

Forum is model-agnostic. It talks to whatever you point it at and never requires a
specific vendor account. Everything ships with a deterministic stub so the tests and
examples run offline; to drive a real model, give Forum an executor. There are three
ways, listed most account-free first.

## A local model, no account needed

Point Forum at any OpenAI-compatible server (Ollama, LM Studio, llama.cpp, vLLM):

```bash
forum submit "ship a login API with docs" --chat-url http://localhost:11434/v1/chat/completions --model llama3
```

Or run any model command directly, one invocation per task:

```bash
forum submit "ship a login API with docs" --cmd "ollama run llama3"
```

Neither needs a key. `--cmd` is the most agnostic option: any program that takes a
prompt as its last argument is a valid executor, so Forum stays independent of any one
provider and its updates.

## Persistent tier config

For repeated local runs, put the default executor and tier policy in TOML and pass
it to `submit`, `serve`, or `mcp`:

```toml
[runtime.default]
chat_url = "http://localhost:11434/v1/chat/completions"
model = "llama3"

[runtime.tiers.cheap]
chat_url = "http://localhost:11434/v1/chat/completions"
model = "phi3"

[runtime.tiers.capable]
cmd = "ollama run llama3"

[runtime.tiers.frontier]
chat_url = "http://localhost:8000/v1/chat/completions"
model = "qwen2.5-coder"
```

```bash
forum submit "ship a login API with docs" --runtime-config forum-runtime.toml
forum serve --runtime-config forum-runtime.toml
forum mcp --runtime-config forum-runtime.toml
forum runtime inspect --runtime-config forum-runtime.toml
forum context preflight "ship a login API with docs" --use-capsule-context --request-context-token-budget 80
```

Config files name environment variables with `api_key_env`; they do not store key
values. Command-line executor flags still override the file for a single run.
`forum runtime inspect` accepts those same flags and prints the merged runtime
policy, roster tier coverage, and missing executor issues without running any
command or probing any endpoint.
`forum context preflight` uses the same approximate-token budget logic as submit
to show whether optional capsule context would be retained, trimmed, or omitted
before planning starts.

## A hosted model

Any OpenAI-compatible cloud works through the same `--chat-url`, with a key:

```bash
export OPENAI_API_KEY=sk-...
forum submit "ship a login API with docs" --chat-url https://api.openai.com/v1/chat/completions --model gpt-4o-mini --api-key-env OPENAI_API_KEY
```

The Anthropic API has a dedicated executor:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
forum submit "ship a login API with docs" --api --model claude-sonnet-4-6
```

## The daemon and MCP

The same executor flags apply to the daemon and the MCP server:

```bash
forum serve --chat-url http://localhost:11434/v1/chat/completions --model llama3
forum mcp --cmd "ollama run llama3"
```

Without an executor flag, routing and the ledger commands still work; planning and
submitting return a clear message asking for a model.

## Inspect the record

```bash
forum ledger verify
forum ledger show --limit 20
```

## The real-model proof (gated test)

A gated integration test makes live Anthropic API calls (it costs money) and is
skipped by default. To run it:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export FORUM_RUN_REAL=1
pytest tests/test_real_model.py -v
```

It runs a full `submit` and a `submit_one` through `ApiExecutor` and asserts the ledger
is witnessed and deep-verifiable end to end. The same loop runs against any of the
executors above.
