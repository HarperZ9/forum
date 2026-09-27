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
