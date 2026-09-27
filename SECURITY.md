# Security and trust model

Forum orchestrates work: it runs commands and calls models, and it can serve those
capabilities over HTTP and MCP. That power is the thing to be careful with. This
document states what Forum does, what it guarantees, and how to run it safely.

## What Forum does with your machine and your keys

- **It runs commands.** `SubprocessExecutor` launches the command you configure, once
  per task, through the vendored `safe_spawn` helper. The model's planned instruction is
  passed to that command as a separate argv element, except to claude and codex, which
  read it on stdin.
- **It calls models.** `ApiExecutor` sends prompts to the Anthropic API over HTTPS, with
  a request timeout.
- **It can listen.** The daemon serves HTTP, and the MCP surface speaks JSON-RPC on
  stdio.

## Guarantees

- **No shell, and batch targets are checked.** `SubprocessExecutor` starts the child
  through `safe_spawn`, which uses an argument vector and never invokes a shell, so there
  is no POSIX shell-injection surface (no globbing, no `;`, no `$()`). The task
  instruction is a separate argv element, or stdin for claude and codex, whose npm
  installs are batch shims on Windows. On Windows a `.cmd` or `.bat` target is run by
  CreateProcess through `cmd.exe`, whose metacharacters Python's argv quoting does not
  escape; for that case `safe_spawn` refuses an argument holding
  `" % ^ & | < > !`, a carriage return, a line feed, or an unquoted `)` with
  `UNSAFE_ARGUMENT`, so a batch target cannot be injected through the instruction. This
  is not a claim of "no shell-injection surface" for a batch target: it is an explicit
  refusal of the characters that would create one.
- **Children start isolated.** The executable is resolved to an absolute path (a bare
  name is looked up on `PATH` only, the working folder is never searched by name, and
  `NoDefaultCurrentDirectoryInExePath=1` is set on Windows). A `PATH` entry that
  reaches the working folder (the folder forum runs in, or a folder named for the
  child) is skipped for the lookup and removed from the child's `PATH`, whether it
  names the folder directly, through a junction or symlink, through an alias the name
  check misses (matched by device and file index: the `\\?\` prefix and the admin
  share on Windows, a bind mount on Linux), or with quotes cmd.exe reads as the
  folder. Each kept entry is handed to the child as its resolved real folder, so a
  `PATH` link repointed between the check and the start can no longer redirect
  forum's lookup or the child's own. A swap of the file itself, or of a folder inside
  its real folder, between the check and the start still races; it needs write
  access to a folder `PATH` already trusts. The exact folder of the running
  interpreter and, on Windows, the exact Windows, System32 and SysWOW64 folders are
  always kept, and a working folder that is one of them is not guarded, because
  forum already runs code from there. A filesystem root or a folder that holds the
  home folder narrows to that folder itself, so the tools installed below it stay
  while the folder's own entry drops. On a filesystem that reports no file index,
  every entry on the working folder's device is dropped. A drive-relative name such
  as `C:claude` is refused. The child runs in a new private empty folder,
  and its environment is an allowlist (the platform base plus the variables the launch
  names in `FORUM_CHILD_ENV`, not the whole environment). A Python target gets `-P`. A
  known agent CLI (claude, codex, gemini, opencode) is started with its isolation
  profile; an unproven profile is refused unless `FORUM_ALLOW_EXEC_CLI` names it. Both
  launch variables apply to every configured command: `--cmd`, the tier flags and
  `--runtime-config`.
- **Keys live in the environment, not in the code or the record.** `ApiExecutor` reads
  the API key from an environment variable (`ANTHROPIC_API_KEY` by default). The key is
  sent only in the request header; it is never written to the ledger and never logged.
  A command child no longer inherits the whole environment, so a provider key is not
  handed to it unless the launch adds it to the allowlist.
- **The record is content-addressed and redactable.** Prompts and outputs are stored
  by the hash of their bytes. A sensitive payload body can be dropped to its hash alone
  and the chain still verifies (`verify(deep=True)` tolerates absent bodies), so the
  ledger can be kept hash-only for sensitive runs.
- **The HTTP parser is bounded.** A request body is capped (1 MiB), a slow or truncated
  request times out, and conflicting `Content-Length` or any `Transfer-Encoding` header
  is rejected, so the hand-written parser cannot be hung or smuggled through.

## The daemon and the gates

- **`forum serve` requires a token by default.** It generates a local bearer token at
  startup and prints it to stderr; a client sends it as `Authorization: Bearer <token>`.
  `--no-auth` turns this off and is refused on any non-loopback `--host`. The daemon also
  runs transport defenses on every request except `/health`: an `Origin`, when present,
  must be the daemon's own origin, a loopback host on the daemon's port, so a page
  another local program serves is refused (else 403); on a daemon without a token, a
  `Host`, when present, must be a loopback name compared without case, which stops a
  rebound DNS name (else 403); and a POST/PUT/PATCH with a body must be
  `application/json` (else 415). With a token, any host name is served, because a
  rebinding page never holds the token. It still binds `127.0.0.1` by default.
- **A reverse proxy must meet the transport checks.** There is no rate limiting or
  built-in TLS, so put a TLS-terminating reverse proxy in front of any network bind,
  and keep the token on: the proxy passes the `Authorization` header through, and the
  daemon serves the public host name. An open daemon (`--no-auth`) serves only a
  loopback `Host`, so a proxy in front of one must forward `Host: 127.0.0.1` or
  `localhost`, or every request gets 403. A browser page reached through the proxy
  sends the proxy's `Origin`, which the daemon refuses with 403. Rewrite that header
  at the proxy only while the token is on, because the token is then what stops a
  cross-site request.
- **A gate decision needs a raised, pending gate.** An approval, edit or rejection
  counts only when it is chained to the `gate_pending` it resolves and was written after
  it, so a decision recorded before a gate opens cannot let a gated wave run. Over MCP
  the decision tools are listed only with the `--allow-gate-decisions` launch grant (for
  `forum mcp` and for an embedded `McpSurface` alike), so a connected model cannot
  approve its own gate by default; approvals belong to a person on the CLI, or an
  authenticated HTTP identity.
- **An approval covers one run and the content it showed.** A resume continues the run
  of the same plan (a digest of every task), and each gate records the instructions it
  shows and a digest of its wave; a decision counts only for a gate that showed the
  content about to run. A different or rewritten plan raises a gate of its own, and an
  edit may rewrite only tasks of the gated wave.
- **An authenticated decision outranks an asserted one.** A decision made with a
  verified token cannot be reversed by a later decision a caller only asserted (a CLI
  user, an MCP client, an HTTP call with auth off). Within one standing, the latest
  decision wins.
- **Model output is untrusted input.** The Coordinator's plan and a task's instruction
  come from a model. If you wire an executor that can touch real systems, treat those
  instructions as untrusted: a prompt-injected or mistaken plan can ask a command to do
  something you did not intend.

## Running safely

- Run the daemon and any real executor as an unprivileged user, in a container or other
  sandbox, with only the filesystem and network access the work needs.
- Keep the ledger directory on storage you control; it contains the prompts and outputs.
- Scope the API key to the minimum, and rotate it if a ledger that recorded sensitive
  prompts is shared.
- Prefer the deterministic stub executors for tests and demos; reach for a real model
  only when you mean to.

## Reporting a vulnerability

Please report security issues privately rather than opening a public issue: open a
GitHub private security advisory at
https://github.com/HarperZ9/forum/security/advisories/new (or reach the author via
https://github.com/HarperZ9). We will acknowledge it and work a fix before any public
disclosure.
