# Forum Usage

Forum coordinates agents and model executors through a replayable causal
ledger. It is designed for local CLIs, MCP hosts, HTTP adapters, and larger
Project Telos workflows that need a trustworthy path from request to answer.

## Install

```bash
python -m pip install forum-engine
```

From a source checkout:

```bash
python -m pip install -e ".[dev]"
```

## Run

```bash
forum status --json
forum doctor --json
forum demo --json
forum --help
```

Example scripts:

```bash
python examples/demo.py
python examples/run_request.py
python examples/run_resume.py
python examples/run_context_pressure.py
python examples/run_context_capsule.py
python examples/run_delivery_profile.py
```

## Codex route-preflight skill asset

Use the reviewed `forum-route-preflight` Codex skill before a Forum model run to preview routing, context pressure, runtime readiness, and the prose contract. The helper is advisory only: it never calls `forum submit`, never runs the configured model command, and keeps `decision.safe_to_submit: false`.

There are two distribution paths:

1. **Standalone ZIP release.** This is the current skill release path. It uses the GitHub tag `forum-route-preflight-v0.1.0`, attaches `forum-route-preflight-skill-20260907-final.zip`, and marks the release `--latest=false` so it does not replace the engine release line. It does not bump `forum-engine`, push a `v*` tag, or publish to PyPI.
2. **Engine package asset.** Future `forum-engine` releases that include this source change carry the same four reviewed files under `forum/skills/forum-route-preflight/`, with `forum/skills/forum-route-preflight.sha256` recording their hashes.

Download and verify the standalone ZIP without cloning the repository:

```bash
python - <<'PY'
from hashlib import sha256
from pathlib import Path
from urllib.request import urlretrieve
from zipfile import ZipFile

url = "https://github.com/HarperZ9/forum/releases/download/forum-route-preflight-v0.1.0/forum-route-preflight-skill-20260907-final.zip"
expected = "1827a9673414e73722ba7bd74be15316534bb6c66fc55ecc26845a5e5c953450"
archive = Path("forum-route-preflight-skill-20260907-final.zip")
target = Path("forum-route-preflight-skill")
urlretrieve(url, archive)
actual = sha256(archive.read_bytes()).hexdigest()
if actual != expected:
    raise SystemExit(f"archive hash mismatch: {actual}")
with ZipFile(archive) as zf:
    zf.extractall(target)
print(target.resolve())
PY
```

Copy the packaged asset from an installed `forum-engine` release that includes this source change:

```bash
python - <<'PY'
import hashlib
import shutil
from importlib.resources import files
from pathlib import Path

source = files("forum") / "skills" / "forum-route-preflight"
manifest = files("forum") / "skills" / "forum-route-preflight.sha256"
target = Path("forum-route-preflight")
shutil.copytree(source, target, dirs_exist_ok=True)
for line in manifest.read_text(encoding="utf-8").splitlines():
    digest, relative = line.split(maxsplit=1)
    data = (files("forum") / "skills" / relative).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise SystemExit(f"packaged skill hash mismatch: {relative}")
print(target.resolve())
PY
```

The asset was validated against the `forum-engine==1.13.0` CLI/API shape; revalidate it before claiming compatibility with another Forum version. The shareable helper receipt stores only a task-text hash at top level. Failed subprocess and invalid-JSON diagnostics store stdout/stderr byte counts and SHA-256 digests, not raw output. Successful JSON is scrubbed for exact helper-supplied task text, paths, runtime commands, chat URLs, model names, API-key environment variable names, and the current values of those supplied API-key variables. It is not a universal secret detector for transformed or previously unknown values.

## Context Pressure

```bash
forum submit "ship the api" --cmd "ollama run llama3" --context-token-budget 4000
forum submit "ship the api" --cmd "ollama run llama3" --request-context-token-budget 1000 --task-context-token-budget 800 --upstream-token-budget 800
```

Forum treats these as approximate tokens using the same 4 bytes/token accounting used
by Index context envelopes. The ledger records `context_budget` entries for retained,
trimmed, and omitted context, and `forum ledger summary --json` reports original,
admitted, and saved context tokens.

## Context Capsules

```bash
forum ledger capsule --json
forum ledger capsule --text
forum submit "ship the api" --cmd "ollama run llama3" --use-capsule-context
```

Capsules compact the current ledger into a deterministic `forum.context-capsule/v1`
brief: latest request, latest answer, task results, quality signals, checkpoint, and
verification state. `--use-capsule-context` feeds that brief through the normal
ContextProvider seam, so existing context budgets still decide how much is admitted.

## Deep Verify Benchmark

```bash
forum bench-deep-verify --json
forum bench-deep-verify --entries 1000,10000 --payload-bytes 256,4096 --storage memory --storage file-batched --redaction-ratio 0,0.5,1 --json --out deep-verify.json
```

`bench-deep-verify` measures the scaling cost of the causal ledger's integrity checks.
It reports chain-only `verify()`, payload-only `verify_payloads()`, and full
`verify(deep=True)` timings as a `forum.deep-verify-benchmark/v1` receipt. The
variables are entry count, payload body bytes, storage mode, fsync mode, redaction
ratio, warmups, and repeats. Redacted payload bodies are removed before verification,
so the benchmark also shows the content-addressed trade-off: the chain can still
verify when only fingerprints remain, while deep payload rehashing scales with the
payload bodies that are still present.

## Expert Delivery Profiles

```bash
forum humanize "Prior to launch, utilize the module test output." --profile engineer
forum submit "ship the api" --cmd "ollama run llama3" --delivery-profile engineer --json
```

Profiles are deterministic checks, not named-writer mimicry. `operator` is the default
contract; `engineer`, `researcher`, and `executive` add domain-specific expectations.
Submit runs witness `delivery_profile_check` entries, and `forum ledger summary --json`
reports profile checks and flags.

## MCP

Use `forum mcp` when a host needs Forum over stdio.

```bash
forum mcp
```

## Verify

```bash
python -m pytest
python examples/demo.py
```

For public/developer delivery checks:

```bash
python -m public_surface_sweeper . --workspace --json
```

## Boundary

Forum should expose route ids, ledger sequence, payload hashes, model identity,
validation verdicts, and receipt references. Do not require raw private prompts,
credentials, full tool payloads, or private evidence for interop.
