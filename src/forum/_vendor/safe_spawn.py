"""Start a child program without handing it the caller's folder or environment.

Vendored verbatim into each flagship; the conformance kit compares the copy's
SHA-256 with the canonical one, so per-tool choices are arguments, never edits.
Rules: an absolute executable (an override variable must hold one; a PATH walk
skips relative entries, and on Windows a .exe anywhere beats a batch shim); a new
private empty working folder unless the caller names one; an environment
allowlist whose PATH keeps only absolute entries, plus
NoDefaultCurrentDirectoryInExePath=1 on Windows; no cmd.exe metacharacters in
any argument to a .cmd or .bat target; -P and PYTHONSAFEPATH=1 for a Python
target (3.11 or later); the named CLI profile's flags, where an unproven profile
needs a grant naming it. Messages never print a resolved path, an argument or a
value. From articulate 0.5.0 claude_cli.py; safe_spawn.mjs ports it.
"""
import ntpath
import os
import posixpath
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass

SAFE_SPAWN_VERSION = "1.0.0"
BATCH_SUFFIXES = (".cmd", ".bat")
_STARTABLE = (".com", ".exe") + BATCH_SUFFIXES
CMD_UNSAFE = frozenset('"%^&|<>!\r\n')
# cmd.exe ends a parenthesized block at ")" outside quotes. Python quotes an
# argument only when it holds a space or a tab, so ")" counts only without one.
CMD_UNSAFE_UNQUOTED = frozenset(")")
NO_CWD_SEARCH = "NoDefaultCurrentDirectoryInExePath"
DRAIN_SECONDS = 5
WINDOWS_BASE_ENV = (
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE", "TEMP", "TMP",
    "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "USERNAME", "APPDATA", "LOCALAPPDATA",
    "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
    "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "OS")
POSIX_BASE_ENV = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE",
                  "TMPDIR", "TZ", "TERM")
_PYTHON_NAMES = ("python", "pythonw", "python3")


@dataclass(frozen=True)
class Profile:
    """Isolation flags for one agent CLI. `after` goes last: `--tools` takes a list."""
    name: str
    before: tuple = ()
    after: tuple = ()
    env: tuple = ()
    proven: bool = False
    tested: str = ""


PROFILES = {  # the evidence for each lives in PROBES.md
    "claude": Profile("claude", after=("--setting-sources", "user", "--strict-mcp-config",
                                       "--tools", ""),
                      env=("CLAUDE_CONFIG_DIR",), proven=True, tested="2.1.251"),
    # The prompt goes on stdin with "-": a batch shim refuses most punctuation.
    "codex": Profile("codex", before=(
        "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral",
        "--skip-git-repo-check", "--sandbox", "read-only", "--disable", "hooks",
        "--disable", "plugins", "--disable", "memories", "--disable", "apps",
        "-c", "project_doc_max_bytes=0", "-c", "skills.include_instructions=false"),
        env=("CODEX_HOME",), proven=True, tested="0.144.6"),
    "gemini": Profile("gemini"),
    "opencode": Profile("opencode"),
}


class SpawnRefused(RuntimeError):
    """The child was not started. `code` is a stable machine-readable reason."""
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _runnable(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)


def _is_absolute(path, windows):
    # On Windows "\tools" hangs off the current drive, so it needs a drive or share too.
    if windows:
        return ntpath.isabs(path) and bool(ntpath.splitdrive(path)[0])
    return posixpath.isabs(path)


def _get(env, key):
    """A variable by name, case-insensitively, as Windows reads it."""
    return env[key] if key in env else next(
        (v for k, v in env.items() if k.lower() == key.lower()), None)


def _from_absolute(path, exists, windows, suffixes, code):
    if not _is_absolute(path, windows):
        raise SpawnRefused(code, "the configured executable is not an absolute path")
    candidates = [path]
    if windows and ntpath.splitext(path)[1].lower() not in _STARTABLE:
        candidates = [path + s for s in suffixes]
    found = next((c for c in candidates if exists(c)), None)
    if not found:
        raise SpawnRefused(code, "the configured executable is not a runnable file")
    return found


def _path_entries(value, windows):
    """(as written, unquoted) for each PATH entry that is an absolute path."""
    pairs = [(r, r.strip().strip('"')) for r in (value or "").split(";" if windows else ":")]
    return [(r, bare) for r, bare in pairs if bare and _is_absolute(bare, windows)]


def resolve(name, override_var=None, environ=None, exists=None, windows=None):
    """The absolute path of `name` (a bare name, or an absolute path), or SpawnRefused."""
    env = os.environ if environ is None else environ
    exists = _runnable if exists is None else exists
    windows = os.name == "nt" if windows is None else windows
    listed = (_get(env, "PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(";") if windows else []
    suffixes = [s for s in listed if s.lower() in _STARTABLE]
    configured = (_get(env, override_var) or "").strip() if override_var else ""
    if configured:
        return _from_absolute(configured, exists, windows, suffixes, "BAD_OVERRIDE")
    if any(sep in name for sep in ("/", "\\")):
        return _from_absolute(name, exists, windows, suffixes, "BAD_PATH")
    join = ntpath.join if windows else posixpath.join
    dirs = [bare for _, bare in _path_entries(_get(env, "PATH"), windows)]
    groups = [[name + ".exe"], [name + s for s in suffixes]] if windows else [[name]]
    for group in groups:
        for d in dirs:
            for candidate in (join(d, n) for n in group):
                if exists(candidate):
                    return candidate
    hint = f" or set {override_var} to its full path" if override_var else ""
    raise SpawnRefused("NOT_FOUND", f"{name} was not found on PATH; install it{hint}")


def is_batch(path, windows=None):
    """True when Windows would start this file through cmd.exe."""
    windows = os.name == "nt" if windows is None else windows
    return windows and os.path.splitext(path)[1].lower() in BATCH_SUFFIXES


def cmd_unsafe(arg):
    """True when cmd.exe would read part of this argument as a command."""
    if CMD_UNSAFE.intersection(arg):
        return True
    quoted = not arg or " " in arg or "\t" in arg
    return not quoted and bool(CMD_UNSAFE_UNQUOTED.intersection(arg))


def is_python(path):
    base = ntpath.splitext(ntpath.basename(path).lower())[0]  # splits on / and \
    return base in _PYTHON_NAMES or (base.startswith("python3.") and base[8:].isdigit())


def child_env(allow=(), set_env=None, environ=None, windows=None, python=False):
    """The platform base plus `allow`, then `set_env` on top. Nothing else passes."""
    env = os.environ if environ is None else environ
    windows = os.name == "nt" if windows is None else windows
    base = WINDOWS_BASE_ENV if windows else POSIX_BASE_ENV
    wanted = {k.lower() if windows else k for k in (*base, *allow)}
    out = {k: v for k, v in env.items() if (k.lower() if windows else k) in wanted}
    for key in [k for k in out if k.upper() == "PATH"]:  # a "." entry is a cwd search
        out[key] = (";" if windows else ":").join(r for r, _ in _path_entries(out[key], windows))
    forced = dict(set_env or {})
    if python:
        forced["PYTHONSAFEPATH"] = "1"
    if windows:
        forced[NO_CWD_SEARCH] = "1"
    for key, value in forced.items():
        if windows:
            out = {k: v for k, v in out.items() if k.lower() != key.lower()}
        out[key] = value
    return out


def build_argv(exe, args, profile=None, grants=(), windows=None):
    """The full argv, after the profile and batch checks. Raises SpawnRefused."""
    prof = PROFILES.get(profile) if isinstance(profile, str) else profile
    if isinstance(profile, str) and prof is None:
        raise SpawnRefused("UNKNOWN_PROFILE", "no isolation profile has that name")
    if prof is not None and not prof.proven and prof.name not in grants:
        raise SpawnRefused("GRANT_REQUIRED", f"the {prof.name} CLI has no proven isolation "
                                             f"profile; a launch grant must name it")
    pre = ["-P"] if is_python(exe) else []
    argv = [exe, *pre, *(prof.before if prof else ()), *args, *(prof.after if prof else ())]
    if is_batch(exe, windows) and any(cmd_unsafe(a) for a in argv):
        raise SpawnRefused("UNSAFE_ARGUMENT", "a batch-file target was refused: an "
                           "argument holds characters cmd.exe would reinterpret")
    return argv, prof


class Session:
    """A private folder for files the child reads, and an empty working folder."""

    def __init__(self, tmpdir=None, prefix="spawn-"):
        self.root = tempfile.mkdtemp(prefix=prefix, dir=tmpdir)
        self.cwd = os.path.join(self.root, "cwd")
        try:
            os.mkdir(self.cwd)
        except OSError:
            self.close()
            raise

    def write(self, name, text):
        if os.path.basename(name) != name or name in ("", ".", "..", "cwd"):
            raise ValueError("a session file name must be a plain name")
        path = os.path.join(self.root, name)
        with open(path, "x", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return path

    def close(self):
        try:
            shutil.rmtree(self.root)
        except OSError as exc:
            print(f"[safe_spawn] could not remove a private folder ({exc.strerror})",
                  file=sys.stderr)


def _taskkill():
    return os.path.join(_get(os.environ, "SystemRoot") or "C:\\Windows", "System32", "taskkill.exe")


def _stop_tree(proc):
    if os.name == "nt":
        try:
            subprocess.run([_taskkill(), "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=DRAIN_SECONDS, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"[safe_spawn] could not stop the process tree ({type(exc).__name__}); "
                  f"stopping the direct child only", file=sys.stderr)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # the group has already exited
    if proc.poll() is None:
        proc.kill()


def bounded_run(argv, input=None, timeout=None, cwd=None, env=None, label="child"):
    """subprocess.run, except that a timeout stops the whole process tree."""
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                            cwd=cwd, env=env, start_new_session=os.name != "nt")
    try:
        out, err = proc.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired:
        _stop_tree(proc)
        try:
            out, err = proc.communicate(timeout=DRAIN_SECONDS)
        except subprocess.TimeoutExpired:
            print("[safe_spawn] the process tree still holds its pipes after the timeout",
                  file=sys.stderr)
            out = err = None
        raise subprocess.TimeoutExpired(label, timeout, output=out, stderr=err) from None
    except BaseException:
        _stop_tree(proc)
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def run(name, args=(), *, profile=None, override_var=None, input=None, timeout=600,
        allow_env=(), set_env=None, grants=(), cwd=None, files=None, environ=None,
        exists=None, windows=None, tmpdir=None, runner=None):
    """Resolve, check and start `name`; return the CompletedProcess.

    `args` is a list, or a callable taking {name: path} for `files` written to the
    private folder; `cwd` None means a new private empty folder. SpawnRefused comes
    before any start; subprocess.TimeoutExpired passes through.
    """
    windows = os.name == "nt" if windows is None else windows
    exe = resolve(name, override_var, environ, exists, windows)
    label = os.path.basename(name)  # never the resolved path
    if runner is None:
        def runner(*a, **kw):
            return bounded_run(*a, label=label, **kw)
    try:
        session = Session(tmpdir)
    except OSError as exc:
        raise _unavailable("the private folder could not be made", exc) from exc
    try:
        paths = {n: session.write(n, t) for n, t in (files or {}).items()}
        argv, prof = build_argv(exe, list(args(paths) if callable(args) else args),
                                profile, grants, windows)
        env = child_env((*allow_env, *(prof.env if prof else ())), set_env, environ,
                        windows, python=is_python(exe))
        return runner(argv, input=input, timeout=timeout,
                      cwd=session.cwd if cwd is None else cwd, env=env)
    except OSError as exc:
        raise _unavailable(f"{label} could not be started", exc) from exc
    finally:
        session.close()


def _unavailable(what, exc):
    return SpawnRefused("UNAVAILABLE", f"{what} ({exc.strerror or type(exc).__name__})")
