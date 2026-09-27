"""The release workflow: least-privilege jobs, a re-runnable PyPI upload, and a GitHub Release that
carries the wheel, the sdist and SHA256SUMS.txt. Read as text: the dev extras carry no YAML parser."""
import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _top_level(text: str) -> dict[str, str]:
    blocks, key = {}, None
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):(.*)$", line)
        if m:
            key = m.group(1)
            blocks[key] = m.group(2).strip() + "\n"
        elif key:
            blocks[key] += line + "\n"
    return blocks


def _jobs(text: str) -> dict[str, str]:
    blocks, key = {}, None
    for line in _top_level(text)["jobs"].splitlines():
        m = re.match(r"^  ([A-Za-z_][\w-]*):\s*$", line)
        if m:
            key = m.group(1)
            blocks[key] = ""
        elif key:
            blocks[key] += line + "\n"
    return blocks


def _permissions(job: str) -> dict[str, str]:
    m = re.search(r"^    permissions:\s*(\{\})?\s*\n((?:      .*\n)*)", job, re.M)
    assert m, "the job declares no permissions block"
    pairs = re.findall(r"^      ([\w-]+):\s*(\w+)", m.group(2), re.M)
    return dict(pairs)


def test_the_workflow_grants_nothing_by_default():
    assert _top_level(_text())["permissions"].strip() == "{}"


def test_each_job_holds_only_the_permission_it_needs():
    jobs = _jobs(_text())
    assert set(jobs) == {"build", "publish", "github-release"}
    assert _permissions(jobs["build"]) == {"contents": "read"}
    assert _permissions(jobs["publish"]) == {"id-token": "write"}
    assert _permissions(jobs["github-release"]) == {"contents": "write"}


def test_the_pypi_upload_can_be_rerun():
    publish = _jobs(_text())["publish"]
    assert "pypa/gh-action-pypi-publish@" in publish
    assert re.search(r"^\s+skip-existing:\s*true\s*(#.*)?$", publish, re.M)


def test_the_build_writes_checksums_for_the_wheel_and_the_sdist():
    build = _jobs(_text())["build"]
    assert re.search(r"sha256sum \*\.whl \*\.tar\.gz > \S*SHA256SUMS\.txt", build)
    assert "GITHUB_REF_NAME" in build, "the build does not check the tag against the version"
    assert "_vendor/safe_spawn.py" in build, "the build does not check the vendored helper in the wheel"


def test_the_github_release_carries_wheel_sdist_and_checksums():
    release = _jobs(_text())["github-release"]
    assert re.search(r"needs:\s*\[?\s*build,\s*publish\s*\]?", release)
    assert "gh release create" in release
    for asset in ("dist/*.whl", "dist/*.tar.gz", "SHA256SUMS.txt"):
        assert asset in release, f"the release does not attach {asset}"
    assert "sha256sum -c" in release, "the release does not verify the checksums it attaches"


def test_checkouts_do_not_keep_the_token():
    for name, job in _jobs(_text()).items():
        if "actions/checkout@" in job:
            assert "persist-credentials: false" in job, f"{name} keeps the checkout token"


# Review findings F6 and F9: nothing reaches PyPI before the suite passes at the
# tagged commit, the installed wheel reports the tag's version, and the release
# stops when PyPI serves files other than the ones the checksums name.

def test_publish_waits_for_the_test_suite():
    jobs = _jobs(_text())
    testing = [name for name, job in jobs.items() if re.search(r"\bpytest\b", job)]
    assert testing, "no release job runs the test suite"
    needs = re.search(r"needs:\s*\[?([^\]\n]*)", jobs["publish"]).group(1)
    assert any(name in needs for name in testing), "publish does not wait for the tests"


def test_the_suite_runs_before_the_build():
    build = _jobs(_text())["build"]
    assert build.index("pytest") < build.index("python -m build"), "the build runs before the tests"


def test_the_build_compares_the_installed_version_to_the_tag():
    build = _jobs(_text())["build"]
    assert re.search(r'forum --version\)"?\s*=\s*"?forum \$\{GITHUB_REF_NAME#v\}', build), \
        "the build never compares the installed command's version to the tag"
    assert re.search(r'importlib\.metadata.*GITHUB_REF_NAME|GITHUB_REF_NAME.*importlib\.metadata',
                     build, re.S), "the build never compares the installed metadata to the tag"


def test_the_release_checks_pypi_holds_the_same_files():
    jobs = _jobs(_text())
    release = jobs["github-release"]
    assert "pypi.org/pypi/" in release, "nothing compares PyPI's digests to SHA256SUMS"
    assert release.index("pypi.org/pypi/") < release.index("gh release create"), \
        "the PyPI comparison runs after the release is cut"
    assert "SHA256SUMS.txt" in release[: release.index("gh release create")]
