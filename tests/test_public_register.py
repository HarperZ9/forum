"""Public surfaces carry no private-line names, internal plan labels, local paths,
or the stale claims the readiness review flagged.

The shipped package, the README and the other public documents are the public
face: a reader who finds a label there has no way to look it up.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_NAMES = ("sofer", "orca", "behavior-transform", "behavior transform")

# Internal plan labels a public reader cannot resolve: work-package and queue
# numbers, and the file names of internal review documents.
INTERNAL_LABELS = {
    "queue label Q0": re.compile(r"\bQ0\b"),
    "queue label Q19": re.compile(r"\bQ19\b"),
    "work-package label WP<n>": re.compile(r"\bWP\d+"),
    "review file name audit-*": re.compile(
        r"\baudit-[\w-]+\.(?:md|txt|json|html|pdf)\b|\baudit-forum\b", re.IGNORECASE
    ),
}
PUBLIC_DOCS = ("README.md", "CHANGELOG.md", "SECURITY.md", "RUNNING.md")
# The vendored helper must stay byte-identical to its pinned hash
# (tests/test_vendored.py), so it is checked there and exempt here.
VENDORED = ROOT / "src" / "forum" / "_vendor"
TEXT_SUFFIXES = {".py", ".toml", ".md", ".yaml", ".yml", ".json", ".txt", ".sha256"}


def _src_files():
    return list((ROOT / "src").rglob("*.py")) + list((ROOT / "src").rglob("*.toml"))


def _public_text_files():
    shipped = [
        path for path in (ROOT / "src").rglob("*")
        if path.is_file()
        and path.suffix.lower() in TEXT_SUFFIXES
        and "__pycache__" not in path.parts
        and VENDORED not in path.parents
    ]
    return shipped + [ROOT / name for name in PUBLIC_DOCS]


def test_the_label_scan_covers_the_shipped_code_and_the_public_docs():
    files = _public_text_files()
    rel = {path.relative_to(ROOT).as_posix() for path in files}
    assert "src/forum/executor.py" in rel
    assert "src/forum/flagship.py" in rel
    assert set(PUBLIC_DOCS) <= rel
    assert not any(name.startswith("src/forum/_vendor/") for name in rel)


def test_the_label_patterns_catch_the_forms_they_deny_and_spare_plain_words():
    # A scan that matches nothing proves nothing, so each pattern must catch the
    # forms that shipped before this check existed, and pass ordinary prose.
    caught = {
        "queue label Q0": ["from the Q0 PROBES.md", "its Q0 isolation profile"],
        "queue label Q19": ["deferred to Q19", "(Q19)"],
        "work-package label WP<n>": ["WP2 extends this", "WP1 public-register", "(WP10)"],
        "review file name audit-*": ["(`audit-forum.md`, section 5)", "see audit-forum"],
    }
    spared = ["an auditable verdict", "the audit trail", "Q01 results", "WPA2 Wi-Fi", "Q0x"]
    for label, samples in caught.items():
        for sample in samples:
            assert INTERNAL_LABELS[label].search(sample), f"{label} misses {sample!r}"
        for sample in spared:
            assert not INTERNAL_LABELS[label].search(sample), f"{label} flags {sample!r}"


@pytest.mark.parametrize("label", sorted(INTERNAL_LABELS))
def test_public_files_carry_no_internal_plan_labels(label):
    pattern = INTERNAL_LABELS[label]
    hits = []
    for path in _public_text_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(ROOT).as_posix()}:{number}")
    assert hits == [], f"{label} appears in public files: {hits}"


def test_src_ships_no_private_line_names():
    for path in _src_files():
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for name in PRIVATE_NAMES:
            assert name not in text, f"{path.name} ships the private name {name!r}"


def test_src_ships_no_private_line_probe_keywords():
    # "seed", "kun" and "line" are English words; check the roster keyword list
    # and the flagship module do not carry the private-line codename tokens.
    roster = (ROOT / "src/forum/manifests/default-roster.toml").read_text(encoding="utf-8").lower()
    for token in ('"seed"', '"kun"', '"sofer"', '"orca"', '"transform"', '"private"', '"line"'):
        assert token not in roster, f"the roster keeps the private keyword {token}"
    flagship = (ROOT / "src/forum/flagship.py").read_text(encoding="utf-8")
    assert "PRIVATE_LINE_ROUTE_PROBE" not in flagship


def test_readme_has_no_local_paths():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for needle in ("C:\\", "E:\\", "D:\\", "/home/", "/Users/", "/mnt/", "/dev/"):
        assert needle not in text, f"README carries a local path fragment {needle!r}"


def test_readme_dropped_the_operator_surface_and_fair_source_badge():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Operator surface" not in text
    assert "operator-spine" not in text
    assert "Forum%20Fair--Source" not in text  # the stale license badge
    assert "FSL--1.1--MIT" in text


def test_readme_lists_the_flight_recorder_commands():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for cmd in ("import-trace", "grade", "export-gradable", "mine"):
        assert cmd in text, f"README omits the {cmd!r} command"


def _release_notes(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    start = text.index(f"## {version} ")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


def test_the_upgrade_notes_cover_each_change_a_1_14_setup_meets():
    notes = _release_notes("1.15.0")
    section = notes[notes.index("### Upgrading from 1.14"):]
    section = section[: section.find("\n### ", 1)]
    for change, needle in {
        "daemon clients need the token": "Authorization: Bearer",
        "provider keys need FORUM_CHILD_ENV": "FORUM_CHILD_ENV=ANTHROPIC_API_KEY",
        "relative paths resolve in an empty folder": "private empty",
        "batch targets refuse multi-line tasks": "UNSAFE_ARGUMENT",
        "the daemon checks Host": "`Host`",
        "the daemon checks Origin": "`Origin`",
        "MCP gate decisions need the grant": "--allow-gate-decisions",
    }.items():
        assert needle in section, f"the upgrade notes omit: {change}"


def test_the_readme_puts_gated_runs_and_resume_on_the_python_api_only():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Approval gates and resume run through the Python API." in readme
    assert "the Python API and the daemon" not in readme
    # The claim holds while the daemon's submit handler reads neither field.
    actions = (ROOT / "src/forum/http_actions.py").read_text(encoding="utf-8")
    submit = actions[actions.index("async def _submit"):]
    assert "gates" not in submit and "resume" not in submit


def test_public_docs_drop_the_claims_the_review_disproved():
    docs = {name: (ROOT / name).read_text(encoding="utf-8") for name in PUBLIC_DOCS}
    for name, text in docs.items():
        flat = " ".join(text.split())
        assert "never the working folder" not in flat, name
        assert "never in the folder Forum runs in" not in flat, name
        assert "Each run is keyed to its own plan entry" not in flat, name
    security = " ".join(docs["SECURITY.md"].split())
    assert "forward `Host: 127.0.0.1`" in security  # the reverse-proxy requirement


def test_security_md_does_not_claim_no_shell_injection_surface_outright():
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    # The old flat claim is gone; the batch-target refusal is stated instead.
    assert "so there is no shell-injection surface (no globbing, no `;`, no `$()`)." not in text
    assert "UNSAFE_ARGUMENT" in text
    assert "batch target cannot be injected" in text
