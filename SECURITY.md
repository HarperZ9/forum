# Security and trust model

Forum orchestrates work: it runs commands and calls models, and it can serve those
capabilities over HTTP and MCP. That power is the thing to be careful with. This
document states what Forum does, what it guarantees, and how to run it safely.

## What Forum does with your machine and your keys

- **It runs commands.** `SubprocessExecutor` launches the command you configure, once
  per task. The model's planned instruction is passed to that command.
- **It calls models.** `ApiExecutor` sends prompts to the Anthropic API over HTTPS.
- **It can listen.** The daemon serves HTTP, and the MCP surface speaks JSON-RPC on
  stdio.

## Guarantees

- **No shell.** `SubprocessExecutor` uses `asyncio.create_subprocess_exec`, which takes
  an argument vector and never invokes a shell. The task instruction is a separate
  argv element, so there is no shell-injection surface (no globbing, no `;`, no `$()`).
- **Keys live in the environment, not in the code or the record.** `ApiExecutor` reads
  the API key from an environment variable (`ANTHROPIC_API_KEY` by default). The key is
  sent only in the request header; it is never written to the ledger and never logged.
- **The record is content-addressed and redactable.** Prompts and outputs are stored
  by the hash of their bytes. A sensitive payload body can be dropped to its hash alone
  and the chain still verifies (`verify(deep=True)` tolerates absent bodies), so the
  ledger can be kept hash-only for sensitive runs.
- **The HTTP parser is bounded.** A request body is capped (1 MiB), a slow or truncated
  request times out, and conflicting `Content-Length` or any `Transfer-Encoding` header
  is rejected, so the hand-written parser cannot be hung or smuggled through.

## What Forum does NOT do (run it accordingly)

- **The daemon has no authentication or authorization.** It binds `127.0.0.1` by
  default. Do not bind it to a public interface (`forum serve --host 0.0.0.0`) without
  putting an authenticating, TLS-terminating reverse proxy in front of it. There is no
  built-in auth, rate limiting, or TLS in v1.
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
