"""The route-preflight helper runs forum with -P, so a planted forum.py is not imported.

Falsifier for the audit S1 skill-helper finding: 1.14.0 ran ``sys.executable -m
forum`` so a ``forum.py`` in the working folder shadowed the installed package.
"""
import json
import os
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _helper_bytes() -> bytes:
    return files("forum").joinpath(
        "skills/forum-route-preflight/scripts/forum_route_preflight.py"
    ).read_bytes()


def test_the_helper_invokes_forum_with_safe_path():
    src = _helper_bytes().decode("utf-8")
    assert '"-P"' in src or "'-P'" in src
    assert 'sys.executable, "-m", "forum"' not in src
    assert 'sys.executable, "-P", "-m", "forum"' in src


def test_a_planted_forum_module_in_the_working_folder_is_not_imported(tmp_path):
    # Write the packaged helper to disk, plant a hostile forum.py in the folder we
    # run it from, and confirm forum route still returns the real route, not the
    # plant's output.
    helper = tmp_path / "forum_route_preflight.py"
    helper.write_bytes(_helper_bytes())
    run_from = tmp_path / "run_from"
    run_from.mkdir()
    (run_from / "forum.py").write_text(
        "import sys\nsys.stdout.write('PLANTED\\n')\nsys.exit(0)\n", encoding="utf-8"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src"), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    # Invoke the helper the ordinary way (no outer -P). The fix is internal: the
    # helper runs `python -P -m forum`, so the planted forum.py in cwd cannot
    # shadow the real package for the route/preflight/runtime subprocess calls.
    proc = subprocess.run(
        [sys.executable, str(helper), "route the api database task"],
        cwd=str(run_from), env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    route = payload["sections"]["route"] if "sections" in payload else payload
    blob = json.dumps(payload)
    assert "PLANTED" not in blob
    # the real forum route returns a decided lane / candidates structure
    assert "decided" in blob or "route" in route
