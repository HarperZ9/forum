"""Start a child program without handing it the caller's folder or environment.

Vendored verbatim into each flagship; the conformance kit compares the copy's
SHA-256 with the canonical one, so per-tool choices are arguments, never edits.
Rules: an absolute executable (an override variable must hold one; a PATH walk
skips relative entries and entries that reach a working folder, and on Windows a
.exe anywhere beats a batch shim; a bare name holding ":" is refused); a new
private empty working folder unless the caller names one; an environment
allowlist whose PATH keeps what the walk keeps (on POSIX, /bin:/usr/bin when that
leaves nothing, since an empty PATH means the current folder there), plus
NoDefaultCurrentDirectoryInExePath=1 on Windows; no cmd.exe metacharacters in
any argument to a .cmd or .bat target; -P and PYTHONSAFEPATH=1 for a Python
target (3.11 or later); the named CLI profile's flags, where an unproven profile
needs a grant naming it. Messages never print a resolved path, an argument or a
value. From articulate 0.5.0 claude_cli.py; safe_spawn.mjs ports it.

The working folders are the caller's current folder and the folder named for the
child. An entry reaches one when, resolved through links, it is that folder or
lies below it, by name or by file identity; on a filesystem without file indices,
any folder on the working folder's device counts. A filesystem root or a folder
holding the home folder counts only as itself. The interpreter's folder and, on
Windows, the Windows, System32 and SysWOW64 folders always stay, and a working
folder that is one of them guards nothing: the caller already runs code from
there. Each kept entry becomes its real folder, so a link repointed after the
check cannot change what starts. Windows PATH is read as cmd.exe reads it, and
an entry whose folder holds the PATH separator leaves: programs disagree on it.
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

SAFE_SPAWN_VERSION = "1.0.1"
POSIX_FALLBACK_PATH = "/bin:/usr/bin"
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


def _identity(path):
    """(device, file index), the index 0 where the filesystem keeps none; None if unreadable."""
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    return st.st_dev, st.st_ino


def _same(a, b, unsure):
    """One folder by identity. With `unsure`, a folder without a file index matches any
    folder on its device, since such a filesystem can hide a second name for it."""
    if a is None or b is None or a[0] != b[0]:
        return False
    return a[1] == b[1] != 0 or (unsure and 0 in (a[1], b[1]))


def _real(path):
    """`path` resolved through links, or None when it cannot be read."""
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return None


def _chain(here):
    """(name, identity) for the resolved folder `here`, then each folder above it."""
    if not here:
        return []
    out = [(os.path.normcase(here), _identity(here))]
    while os.path.dirname(here) != here:
        here = os.path.dirname(here)
        out.append((os.path.normcase(here), _identity(here)))
    return out


def _meets(chain, folder, unsure=False):
    return any(n == folder[0] or _same(k, folder[1], unsure) for n, k in chain)


def _trusted(windows):
    """The exact folders the caller already runs code from; nothing below them."""
    own = [os.path.dirname(sys.executable or "")]
    root = _get(os.environ, "SystemRoot") if windows else ""
    if root:
        own += [root, os.path.join(root, "System32"), os.path.join(root, "SysWOW64")]
    return [c[0] for c in (_chain(_real(f)) for f in own if f) if c]


def _reach_test(cwd, windows):
    """A function giving a PATH entry's real folder, or None when the entry reaches a
    working folder (see above). None on a simulated platform: no real folders to read."""
    if windows != (os.name == "nt"):
        return None  # a simulated platform has no real folders to read
    folders = [] if cwd is None else [cwd]
    try:
        folders.append(os.getcwd())
    except OSError:
        pass  # a deleted working folder: no path reaches it
    home = os.path.expanduser("~")
    home = _chain(_real(home)) if os.path.isabs(home) else []
    trusted = _trusted(windows)
    guarded = [(c[0], len(c) == 1 or _meets(home, c[0])) for c in map(_chain, map(_real, folders))
               if c and not any(_meets(c[:1], t) for t in trusted)]

    def admit(entry):
        real = _real(entry)
        chain = _chain(real)
        if not chain:
            return None
        if any(_meets(chain[:1], t) for t in trusted):
            return real
        if any(_meets(chain[:1] if wide else chain, f, True) for f, wide in guarded):
            return None
        return real
    return admit


def _split(value, windows):
    """(as written, as read) per entry. POSIX reads an entry literally, so a quote or a
    leading space makes it relative there. Windows reads it as cmd.exe does: a ";"
    between double quotes does not split, and every quote goes."""
    if not windows:
        return [(r, r) for r in value.split(":")]
    out, start, quoted = [], 0, False
    for i, ch in enumerate(value):
        if ch == '"':
            quoted = not quoted
        elif ch == ";" and not quoted:
            out.append(value[start:i])
            start = i + 1
    out.append(value[start:])
    return [(r, r.replace('"', "").strip()) for r in out]


def _path_entries(value, windows, admit=None):
    """(to hand on, to search) for each absolute PATH entry that reaches no working folder.

    With `admit`, the folder searched is the entry's real folder. A folder holding the
    separator leaves: Windows programs disagree on a quoted one, and POSIX cannot write
    one. The entry goes on as written only where every reader takes it the same way.
    """
    sep, out = ";" if windows else ":", []
    for raw, bare in _split(value or "", windows):
        if not bare or not _is_absolute(bare, windows):
            continue
        real = admit(bare) if admit else bare
        if real is None or sep in real:
            continue
        same = raw in (bare, f'"{bare}"') and os.path.normcase(real) == os.path.normcase(bare)
        out.append((raw if same else real, real))
    return out


def resolve(name, override_var=None, environ=None, exists=None, windows=None, cwd=None):
    """The absolute path of `name` (a bare name, or an absolute path), or SpawnRefused.

    `cwd` is the folder named for the child; PATH entries reaching it are skipped too.
    """
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
    if windows and ":" in name:  # "C:tool" names a file in the current folder of drive C:
        raise SpawnRefused("BAD_PATH", "a bare name holding a colon was refused; "
                                       "give a bare name or a full path")
    join = ntpath.join if windows else posixpath.join
    admit = _reach_test(cwd, windows)
    dirs = [folder for _, folder in _path_entries(_get(env, "PATH"), windows, admit)]
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


def child_env(allow=(), set_env=None, environ=None, windows=None, python=False, cwd=None):
    """The platform base plus `allow`, then `set_env` on top. Nothing else passes.

    PATH keeps what `resolve` walks; `cwd` is the folder named for the child.
    """
    env = os.environ if environ is None else environ
    windows = os.name == "nt" if windows is None else windows
    base = WINDOWS_BASE_ENV if windows else POSIX_BASE_ENV
    wanted = {k.lower() if windows else k for k in (*base, *allow)}
    out = {k: v for k, v in env.items() if (k.lower() if windows else k) in wanted}
    admit = _reach_test(cwd, windows)
    for key in [k for k in out if k.upper() == "PATH"]:  # a "." entry is a cwd search
        kept = [r for r, _ in _path_entries(out[key], windows, admit)]
        out[key] = ";".join(kept) if windows else (":".join(kept) or POSIX_FALLBACK_PATH)
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
    exe = resolve(name, override_var, environ, exists, windows, cwd)
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
                        windows, python=is_python(exe), cwd=cwd)
        return runner(argv, input=input, timeout=timeout,
                      cwd=session.cwd if cwd is None else cwd, env=env)
    except OSError as exc:
        raise _unavailable(f"{label} could not be started", exc) from exc
    finally:
        session.close()


def _unavailable(what, exc):
    return SpawnRefused("UNAVAILABLE", f"{what} ({exc.strerror or type(exc).__name__})")
