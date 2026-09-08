# Releasing forum-engine

Releases are built and published to PyPI by GitHub Actions (`.github/workflows/release.yml`)
when a version tag is pushed. Publishing is the only outward step and it is deliberately
gated behind a tag and a one-time PyPI setup.

Standalone Codex skill ZIP releases use their own tags, such as `forum-route-preflight-v0.1.0`, and are separate from `forum-engine` releases. They do not bump the engine version, do not use a `v*` tag, and do not publish to PyPI.

## One-time setup (PyPI trusted publishing)

1. Reserve the `forum-engine` name on PyPI, or rely on a pending publisher for the first run.
2. On PyPI, add a Trusted Publisher for this repository:
   - Owner: `HarperZ9`, Repository: `forum`, Workflow: `release.yml`, Environment: `pypi`.

   Trusted publishing lets the workflow upload over OIDC with no API token stored in the repo.
   (Alternative: store a PyPI API token as a repository secret and switch the publish step to use it.)

## Cutting a release

1. Confirm `main` is green (`pytest -q`) and the version in `pyproject.toml` and
   `src/forum/__init__.py` match the release you intend.
2. Update `CHANGELOG.md`.
3. Tag and push:
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
4. The Release workflow builds the sdist and wheel, verifies the wheel installs,
   `forum --version` runs, the default roster loads, and packaged skill assets match
   their reviewed SHA-256 manifest, then publishes to PyPI.
5. Create a GitHub Release with the changelog notes for the tag.

## Verifying a build locally

```bash
python -m build
python -m venv /tmp/v && /tmp/v/bin/pip install dist/*.whl
/tmp/v/bin/forum --version
/tmp/v/bin/python -c "from forum.roster import load_default; print(len(load_default().agents))"
/tmp/v/bin/python - <<'PY'
import hashlib
from importlib.resources import files

manifest = files("forum") / "skills" / "forum-route-preflight.sha256"
for line in manifest.read_text(encoding="utf-8").splitlines():
    digest, relative = line.split(maxsplit=1)
    data = (files("forum") / "skills" / relative).read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest
print("forum-route-preflight skill asset verified")
PY
```

## Standalone route-preflight skill ZIP

A standalone route-preflight skill release is a GitHub Release asset release, not an engine package release. For `forum-route-preflight-v0.1.0`, attach the reviewed `forum-route-preflight-skill-20260907-final.zip` archive with SHA-256 `1827a9673414e73722ba7bd74be15316534bb6c66fc55ecc26845a5e5c953450`.

```bash
gh release create forum-route-preflight-v0.1.0 forum-route-preflight-skill-20260907-final.zip \
  --repo HarperZ9/forum \
  --title "forum-route-preflight v0.1.0" \
  --notes-file RELEASE-NOTES-forum-route-preflight-v0.1.0.md \
  --latest=false
```

Do not bump `pyproject.toml` or `src/forum/__init__.py` for this standalone skill asset. Do not use a `v*` tag unless cutting a normal `forum-engine` release, because `v*` tags trigger the PyPI workflow.

The source-tree package assets under `src/forum/skills/` are for the next normal engine release that includes this change. Until then, the standalone ZIP is the distribution artifact humans can download and extract without cloning the engine source.
