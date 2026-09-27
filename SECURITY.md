# Security and trust model

Forum orchestrates work: it runs commands and calls models, and it can serve those
capabilities over HTTP and MCP. That power is the thing to be careful with. This
document states what Forum does, what it guarantees, and how to run it safely.

## What Forum does with your machine and your keys

- **It runs commands.** `SubprocessExecutor` launches the command you configure, once
  per task, through the vendored `safe_spawn` helper. The model's planned instruction is
  passed to that command as a separate argv element.
- **It calls models.** `ApiExecutor` sends prompts to the Anthropic API over HTTPS, with
  a request timeout.
- **It can listen.** The daemon serves HTTP, and the MCP surface speaks JSON-RPC on
  stdio.

## Guarantees

- **No shell, and batch targets are checked.** `SubprocessExecutor` starts the child
  through `safe_spawn`, which uses an argument vector and never invokes a shell, so there
  is no POSIX shell-injection surface (no globbing, no `;`, no `$()`). The task
  instruction is a separate argv element. On Windows a `.cmd` or `.bat` target is run by
  CreateProcess through `cmd.exe`, whose metacharacters Python's argv quoting does not
  escape; for that case `safe_spawn` refuses an argument holding
  `" % ^ & | < > !`, a carriage return, a line feed, or an unquoted `)` with
  `UNSAFE_ARGUMENT`, so a batch target cannot be injected through the instruction. This
  is not a claim of "no shell-injection surface" for a batch target: it is an explicit
  refusal of the characters that would create one.
- **Children start isolated.** The executable is resolved to an absolute path (a bare
  name is looked up on `PATH` only, never the working folder, and `NoDefaultCurrent`
  `DirectoryInExePath=1` is set on Windows), the child runs in a new private empty
  folder, and its environment is an allowlist (the platform base plus the variables the
  launch names in `FORUM_CHILD_ENV`, not the whole environment). A Python target gets
  `-P`. A known agent CLI (claude, codex, gemini, opencode) is started with its
  isolation profile; an unproven profile is refused unless `FORUM_ALLOW_EXEC_CLI` names
  it.
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
  must be a loopback origin (else 403); a `Host`, when present, must be a loopback name,
  which stops a rebound DNS name (else 403); and a POST/PUT/PATCH with a body must be
  `application/json` (else 415). It still binds `127.0.0.1` by default. There is no rate
  limiting or built-in TLS; put a TLS-terminating reverse proxy in front of any public
  bind.
- **A gate decision needs a raised, pending gate.** An approval, edit or rejection
  counts only when it is chained to the `gate_pending` it resolves and was written after
  it, so a decision recorded before a gate opens cannot let a gated wave run. Over MCP
  the decision tools are listed only with the `--allow-gate-decisions` launch grant, so a
  connected model cannot approve its own gate by default; approvals belong to a person on
  the CLI, or an authenticated HTTP identity.
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
