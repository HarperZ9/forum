"""Public surfaces carry no private-line names, local paths, or the stale claims
the audit flagged.

WP1 public-register cleanup: the shipped package and README are the public face.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_NAMES = ("sofer", "orca", "behavior-transform", "behavior transform")


def _src_files():
    return list((ROOT / "src").rglob("*.py")) + list((ROOT / "src").rglob("*.toml"))


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


def test_security_md_does_not_claim_no_shell_injection_surface_outright():
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    # The old flat claim is gone; the batch-target refusal is stated instead.
    assert "so there is no shell-injection surface (no globbing, no `;`, no `$()`)." not in text
    assert "UNSAFE_ARGUMENT" in text
    assert "batch target cannot be injected" in text
