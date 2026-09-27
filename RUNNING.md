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
provider and its updates. The claude and codex CLIs are the exception: `--cmd "claude -p"`
and `--cmd "codex exec"` receive each task on stdin, which also works through the `.cmd`
shims npm installs on Windows.

A bare command name is looked up on `PATH`, and the folder Forum runs in is never
searched by name. A `PATH` entry inside that folder, such as a project's
`node_modules/.bin`, is skipped too, except the Python environment Forum itself runs
from. Give a full path to run a program that lives there.

Each command runs in a new empty folder with a short environment. Give full paths in
its arguments: `--cmd "python adapter.py"` finds no `adapter.py` in that folder. The
command sees the platform base variables (`PATH`, the home and temp folders and similar)
and no provider keys. Name any others it needs in `FORUM_CHILD_ENV`, for example
`FORUM_CHILD_ENV=ANTHROPIC_API_KEY` for `claude -p` with API-key sign-in, or
`FORUM_CHILD_ENV="OLLAMA_HOST HTTPS_PROXY"`.

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

`forum serve` listens on `127.0.0.1:8080` and prints a bearer token to stderr at
startup (`forum daemon token: ...`). Send it with every request except `GET /health`.
The daemon exposes pre-submit inspection endpoints over the same durable ledger:

```bash
export FORUM_TOKEN=...   # the token forum serve printed
curl -H "Authorization: Bearer $FORUM_TOKEN" http://127.0.0.1:8080/runtime
curl -X POST http://127.0.0.1:8080/context/preflight \
  -H "Authorization: Bearer $FORUM_TOKEN" \
  -H "content-type: application/json" \
  -d '{"request":"continue the run","use_capsule_context":true,"context_token_budget":0}'
curl -X POST http://127.0.0.1:8080/prose/contract \
  -H "Authorization: Bearer $FORUM_TOKEN" \
  -H "content-type: application/json" \
  -d '{"text":"build the API endpoint","profile":"engineer"}'
```

On a loopback address, `forum serve --no-auth` runs without a token.

MCP hosts get the same payloads through `forum.runtime.inspect`,
`forum.context.preflight`, and `forum.prose.contract`.

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
