"""Keep the folder the server runs in out of a command lookup.

The vendored safe_spawn skips relative PATH entries and never searches the
working folder by name. Two routes stayed open, and these guards close them
before safe_spawn runs, without editing the vendored copy:

- an absolute PATH entry that resolves inside the working folder, written
  directly, reached through a junction or a symlink, or put there by a tool (npm
  adds ``<project>/node_modules/.bin``). ``guarded_environ`` drops such entries
  from the environment used for the lookup and for the child's own PATH, so a
  batch shim that looks up ``node`` cannot reach the folder either;
- a drive-relative name such as ``C:claude`` on Windows, which names a file in
  the current folder of that drive. ``check_command_name`` refuses a bare name
  that holds a colon.

Two cases keep their entries. The Python environment forum itself runs from
(an activated project venv) stays on PATH: forum already runs code from there.
And the guard stands down when the working folder is a filesystem root or holds
the user's home folder, where it would drop every entry (a service started in
``/``) or the user's own installs (npm's global folder sits under the profile).
"""
from __future__ import annotations

import os
import sys
from collections.abc import Mapping

from forum._vendor.safe_spawn import SpawnRefused


def check_command_name(name: str, *, windows: bool | None = None) -> None:
    """Raise SpawnRefused(BAD_PATH) for a Windows bare name that holds a colon."""
    windows = os.name == "nt" if windows is None else windows
    if windows and ":" in name and not any(sep in name for sep in ("/", "\\")):
        raise SpawnRefused(
            "BAD_PATH", "a drive-relative command name was refused; give a bare name or a full path"
        )


def _within(path: str, folder: str) -> bool:
    path, folder = os.path.normcase(path), os.path.normcase(folder)
    return path == folder or path.startswith(folder.rstrip("\\/") + os.sep)


def _resolved(path: str) -> str:
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return os.path.abspath(path)


def guarded_environ(
    environ: Mapping[str, str] | None = None, *, cwd: str | None = None
) -> dict[str, str]:
    """A copy of ``environ`` whose PATH holds no entry inside the working folder."""
    env = dict(os.environ if environ is None else environ)
    folder = _resolved(os.getcwd() if cwd is None else cwd)
    home = _resolved(os.path.expanduser("~"))
    if os.path.dirname(folder) == folder or _within(home, folder):
        return env
    own = {_resolved(sys.prefix), _resolved(sys.exec_prefix)}
    for key in [k for k in env if k.upper() == "PATH"]:
        kept = []
        for raw in env[key].split(os.pathsep):
            bare = raw.strip().strip('"')
            if bare and os.path.isabs(bare):
                real = _resolved(bare)
                if _within(real, folder) and not any(_within(real, p) for p in own):
                    continue
            kept.append(raw)
        env[key] = os.pathsep.join(kept)
    return env
