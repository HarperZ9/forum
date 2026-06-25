# Running Forum for real

Everything ships with a deterministic stub so the tests and examples run offline.
To drive a real model, give Forum an executor with credentials.

## With the Anthropic API

Set your key and use the API executor:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
forum submit "ship a login API with docs" --api
```

`--api` uses the Anthropic Messages API (model defaults to `claude-sonnet-4-6`;
override with `--model`). The whole run is witnessed; inspect it afterward with
`forum ledger verify` and `forum ledger show`.

## With a model CLI

Any command that takes a prompt as its last argument works:

```bash
forum submit "ship a login API with docs" --cmd "claude -p"
```

Forum runs the command once per task in a subprocess (no shell, so no injection
surface) and witnesses each result.

## The daemon and MCP

```bash
forum serve --api                 # HTTP daemon, durable ledger, on 127.0.0.1:8080
forum mcp --api                   # MCP server over stdio
```

Without `--api` or `--cmd`, routing and the ledger commands still work; planning
and submitting return a clear error asking for a model.

## The real-model proof (gated test)

A gated integration test makes live API calls (it costs money) and is skipped by
default. To run it:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export FORUM_RUN_REAL=1
pytest tests/test_real_model.py -v
```

It runs a full `submit` and a `submit_one` through `ApiExecutor` and asserts the
ledger is witnessed and deep-verifiable end to end.
