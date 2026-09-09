import hashlib
import tomllib
from importlib.resources import files
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = "skills/forum-route-preflight"
CHECKSUM_RESOURCE = "skills/forum-route-preflight.sha256"
EXPECTED_HASHES = {
    "SKILL.md": "492884f155645d55dc8f5767e3e3bd0350af52587eab6b8834988537424d1ef2",
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


def test_pyproject_packages_route_preflight_skill_assets():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]["forum"]

    assert "manifests/*.toml" in package_data
    assert "skills/forum-route-preflight.sha256" in package_data
    for relative in EXPECTED_HASHES:
        assert f"skills/forum-route-preflight/{relative}" in package_data
