import hashlib
import tomllib
from importlib.resources import files
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = "skills/forum-route-preflight"
CHECKSUM_RESOURCE = "skills/forum-route-preflight.sha256"
EXPECTED_ARCHIVE_HASH = "1827a9673414e73722ba7bd74be15316534bb6c66fc55ecc26845a5e5c953450"
EXPECTED_HASHES = {
    "SKILL.md": "21be47969dc238d27ba764df166e7890e316f602ec11d06970c223644e558fd2",
    "agents/openai.yaml": "103e3d990c3d212c4cd4a533e54e3a5b1384812444fd3ff55d09a570b125f47d",
    "references/validation-cases.md": "14dba75d78bc63ea655e077d2dca7dd5b95f5ee8c2d0759a530307d21995083e",
    "scripts/forum_route_preflight.py": "95775506296e6171eb006d5cd8d1526a047ed19cfcb188d79c02af8c75607879",
}


def _resource_bytes(relative: str) -> bytes:
    return files("forum").joinpath(SKILL_ROOT, relative).read_bytes()


def test_route_preflight_skill_assets_match_reviewed_archive_hashes():
    assert {
        relative: hashlib.sha256(_resource_bytes(relative)).hexdigest()
        for relative in EXPECTED_HASHES
    } == EXPECTED_HASHES


def test_route_preflight_checksum_manifest_matches_assets():
    text = files("forum").joinpath(CHECKSUM_RESOURCE).read_text(encoding="utf-8")
    observed = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        digest, relative = line.split(maxsplit=1)
        observed[relative] = digest

    expected = {
        f"forum-route-preflight/{relative}": digest
        for relative, digest in EXPECTED_HASHES.items()
    }
    assert observed == expected


def test_pyproject_packages_route_preflight_skill_assets_without_version_bump():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]["forum"]

    assert pyproject["project"]["version"] == "1.14.0"
    assert "manifests/*.toml" in package_data
    assert "skills/forum-route-preflight.sha256" in package_data
    for relative in EXPECTED_HASHES:
        assert f"skills/forum-route-preflight/{relative}" in package_data


def test_docs_separate_standalone_zip_from_engine_release():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    usage = (ROOT / "USAGE.md").read_text(encoding="utf-8")
    releasing = (ROOT / "RELEASING.md").read_text(encoding="utf-8")

    docs = "\n".join([readme, usage, releasing])
    assert "forum-route-preflight-v0.1.0" in docs
    assert "--latest=false" in docs
    assert EXPECTED_ARCHIVE_HASH in docs
    assert "does not publish to PyPI" in docs
    assert "Future `forum-engine` releases" in usage
