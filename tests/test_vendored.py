"""The vendored safe_spawn helper stays byte-identical to the canonical 1.0.1 release."""
import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The canonical SHA-256 of safe_spawn.py 1.0.1, from the helper's own SHA256SUMS.
CANONICAL = {"safe_spawn.py": "557d223ba51807a7a2ab89b9bda5c6291a4b4aa2392680e7916c3fdd61bc0a48"}
# The superseded 1.0.0 hash, so the drift test proves it is rejected, not merely absent.
SUPERSEDED = {"safe_spawn.py": "cb2dfa9447380f637d294244c6bdf591db1a4a1abf40312a4671b785b8e1bea6"}


def _records():
    rows = []
    for line in (ROOT / "VENDORED.sha256").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            digest, rel = line.split(None, 1)
            rows.append((digest.lower(), rel.strip().lstrip("*")))
    return rows


def test_every_vendored_copy_matches_its_record_and_the_canonical_hash():
    rows = _records()
    assert rows, "VENDORED.sha256 lists no copies"
    for digest, rel in rows:
        data = (ROOT / rel).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, f"{rel} drifted from its record"
        assert CANONICAL.get(Path(rel).name) == digest, f"{rel} is not a canonical release"


def test_the_record_names_the_packaged_copy():
    assert ("src/forum/_vendor/safe_spawn.py" in {rel for _, rel in _records()})


def test_the_package_imports_the_vendored_helper():
    from forum._vendor import safe_spawn

    assert safe_spawn.SAFE_SPAWN_VERSION == "1.0.1"


def test_a_one_byte_edit_is_caught(tmp_path):
    # The check is only worth something if it fails on drift: flip one byte in a
    # copy and confirm the same comparison the first test makes rejects it.
    data = bytearray((ROOT / "src/forum/_vendor/safe_spawn.py").read_bytes())
    data[-2] ^= 0x01
    assert hashlib.sha256(bytes(data)).hexdigest() != CANONICAL["safe_spawn.py"]


def test_the_superseded_version_is_not_the_pinned_hash():
    # The 1.0.0 helper left routes open (a link repointed between the check and the
    # start, an alias the name check missed, a quoted PATH entry). The record must
    # pin the current bytes, not the superseded ones.
    digest = {d for d, _ in _records()}
    assert SUPERSEDED["safe_spawn.py"] not in digest, "the record still pins superseded 1.0.0"
    assert CANONICAL["safe_spawn.py"] in digest


def test_a_built_wheel_carries_the_same_bytes(tmp_path):
    # When a wheel has been built into dist/, its copy must match the record too,
    # so a packaging step that rewrites line endings fails here and in release.yml.
    wheels = sorted((ROOT / "dist").glob("forum_engine-*.whl")) if (ROOT / "dist").is_dir() else []
    record = {rel: digest for digest, rel in _records()}
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as zf:
            data = zf.read("forum/_vendor/safe_spawn.py")
        assert hashlib.sha256(data).hexdigest() == record["src/forum/_vendor/safe_spawn.py"], wheel.name
