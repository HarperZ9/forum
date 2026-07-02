# Forum Runtime Inspection Spec

Date: 2026-07-02

## Problem

Forum can route work across local cheap, capable, and frontier executors, and it
can persist that mapping in TOML. The operator still has to infer what will
actually run by reading flags, config, and roster policy separately. A platform
execution layer should state its runtime posture before work starts: which model
or command will handle control work, which tiers are configured, which tiers are
missing, and whether the setup is ready for a run.

## Goals

- Add a read-only runtime inspection surface.
- Reuse the same executor/config precedence as `submit`, `serve`, and `mcp`.
- Report default executor identity and per-tier executor identities.
- Report roster tier demand from the built-in roster.
- Report missing tier executors and whether a run is ready.
- Avoid command execution, network calls, and secret output.
- Support both JSON and a concise human text view.

## Non-Goals

- No connectivity probing.
- No model benchmarking.
- No automatic config discovery.
- No mutation of runtime config files.

## CLI Shape

```bash
forum runtime inspect --runtime-config forum-runtime.toml --json
forum runtime inspect --runtime-config forum-runtime.toml
forum runtime inspect --cmd "ollama run llama3" --capable-cmd "ollama run qwen2.5-coder"
```

The subcommand accepts the same executor flags as `submit`, `serve`, and `mcp`.

## Payload Shape

```json
{
  "schema": "forum.runtime.inspect/v1",
  "ready": true,
  "default": {"kind": "chat", "id": "llama3", "source": "config"},
  "tiers": {
    "cheap": {"kind": "chat", "id": "phi3", "source": "config"},
    "capable": {"kind": "cmd", "id": "SubprocessExecutor", "source": "cli"},
    "frontier": {"kind": "fallback", "id": "llama3", "source": "default"}
  },
  "roster": {
    "agents": 28,
    "tiers": {"cheap": 5, "capable": 17, "frontier": 6}
  },
  "issues": []
}
```

## Source Rules

- Config-derived executors report `source: "config"`.
- CLI-derived executors report `source: "cli"`.
- A missing tier that can use the default executor reports `kind: "fallback"`
  and `source: "default"`.
- A missing tier without a default executor reports `kind: "missing"` and adds
  an issue.
- CLI flags override config for the same default or tier, just like execution.

## Acceptance Criteria

- Runtime inspection reports default and tier executors from a config file.
- CLI tier flags override matching config tier entries in the report.
- Missing executor setup returns `ready: false` with clear issues.
- `forum runtime inspect --json` emits the payload.
- `forum runtime inspect` emits a readable text report.
- Existing executor construction behavior remains unchanged.
