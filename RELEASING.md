# Releasing forum-engine

Releases are built and published to PyPI by GitHub Actions (`.github/workflows/release.yml`)
when a version tag is pushed. Publishing is the only outward step and it is deliberately
gated behind a tag and a one-time PyPI setup.

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
4. The Release workflow builds the sdist and wheel, verifies the wheel installs and that
   `forum --version` runs and the default roster loads, then publishes to PyPI.
5. Create a GitHub Release with the changelog notes for the tag.

## Verifying a build locally

```bash
python -m build
python -m venv /tmp/v && /tmp/v/bin/pip install dist/*.whl
/tmp/v/bin/forum --version
/tmp/v/bin/python -c "from forum.roster import load_default; print(len(load_default().agents))"
```
