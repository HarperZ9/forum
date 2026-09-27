"""Every place the version is written agrees with forum.__version__.

The version lives in several files (pyproject, the package, the README badge and
status lines, the flagship status envelope). This guard fails when any one drifts,
so a release cannot ship a half-bumped tree.
"""
import re
import tomllib
from pathlib import Path

from forum import __version__

ROOT = Path(__file__).resolve().parents[1]


def _readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_pyproject_version_matches_the_package():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["version"] == __version__


def test_readme_badge_matches_the_package():
    assert f"version-{__version__}-" in _readme()


def test_readme_current_source_version_matches_the_package():
    assert f"`forum-engine {__version__}` is the current source version" in _readme()


def test_readme_status_line_matches_the_package():
    assert f"The latest release is `forum-engine {__version__}`" in _readme()


def test_flagship_status_current_status_is_prefixed_with_the_version():
    from forum.flagship import status_payload

    current = status_payload()["native"]["current_status"]
    assert current.startswith(f"{__version__} ")


def test_no_readme_version_badge_names_a_different_version():
    # A stray version-X.Y.Z badge for another version would slip past the exact
    # check above; assert every version-N.N.N badge names this version.
    for found in re.findall(r"version-(\d+\.\d+\.\d+)-", _readme()):
        assert found == __version__, f"README badge names {found}, package is {__version__}"
