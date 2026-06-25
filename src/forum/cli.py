from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import shlex
import sys

from forum import __version__

DEFAULT_LEDGER = "forum-ledger"


def _make_executor(args):
    """Pick an executor from flags (the first present wins): --chat-url, --api, --cmd, else None.

    Forum is model-agnostic: --cmd runs any command (a local model CLI needs no
    account), --chat-url talks to any OpenAI-compatible server (local or cloud),
    and --api is one specific provider (Anthropic).
    """
    chat_url = getattr(args, "chat_url", None)
    if chat_url:
        from forum.chat_executor import ChatExecutor

        return ChatExecutor(
            getattr(args, "model", None) or "default",
            base_url=chat_url,
            api_key_env=getattr(args, "api_key_env", None),
        )
    if getattr(args, "api", False):
        from forum.api_executor import ApiExecutor

        return ApiExecutor(args.model) if getattr(args, "model", None) else ApiExecutor()
    cmd = getattr(args, "cmd", None)
    if cmd:
        from forum.executor import SubprocessExecutor

        return SubprocessExecutor(shlex.split(cmd))
    return None


def _open_ledger(directory):
    from forum.ledger import Ledger
    from forum.storage import FileStorage

    return Ledger(FileStorage(directory))


def _cmd_route(args) -> int:
    from forum.roster import load_default
    from forum.routing import LexicalRouter

    result = LexicalRouter().score(args.text, load_default())
    print(json.dumps({
        "decided": result.decided,
        "confidence": result.confidence,
        "needs_escalation": result.needs_escalation,
        "candidates": [{"agent": c.agent, "score": c.score} for c in result.candidates],
    }, indent=2))
    return 0


def _cmd_submit(args) -> int:
    executor = _make_executor(args)
    if executor is None:
        print(
            "submit needs a model executor. Forum is model-agnostic: pass --cmd "
            '"<model cli>" (any command, local models need no account), --chat-url '
            "<openai-compatible url> (e.g. a local Ollama server), or --api (Anthropic).",
            file=sys.stderr,
        )
        return 2
    from forum.budget import RunBudget
    from forum.daemon import build_orchestrator

    budget = None
    if args.max_model_calls is not None or args.max_seconds is not None:
        budget = RunBudget(max_model_calls=args.max_model_calls, max_seconds=args.max_seconds)
    intent_judge = None
    if getattr(args, "judge_intent", False):
        from forum.control import IntentJudge

        intent_judge = IntentJudge()
    orch = build_orchestrator(args.ledger, executor=executor, intent_judge=intent_judge)
    try:
        answer = asyncio.run(orch.submit(args.request, budget=budget))
    except ValueError as exc:
        print(f"submit failed: {exc}", file=sys.stderr)
        return 1
    print(answer)
    print(f"checkpoint: {orch.ledger.checkpoint()}", file=sys.stderr)
    return 0


def _cmd_serve(args) -> int:
    from forum.daemon import serve

    asyncio.run(serve(
        ledger_dir=args.ledger, host=args.host, port=args.port, executor=_make_executor(args)
    ))
    return 0


def _cmd_mcp(args) -> int:
    from forum.daemon import build_orchestrator
    from forum.mcp_surface import serve_stdio

    orch = build_orchestrator(args.ledger, executor=_make_executor(args))
    asyncio.run(serve_stdio(orch))
    return 0


def _cmd_ledger_verify(args) -> int:
    led = _open_ledger(args.ledger)
    print(json.dumps({"chain": led.verify(), "deep": led.verify(deep=True)}, indent=2))
    return 0


def _cmd_ledger_show(args) -> int:
    led = _open_ledger(args.ledger)
    entries = led.replay()
    if args.limit:
        entries = entries[-args.limit:]
    for e in entries:
        print(f"{e.seq:>5}  {e.actor:<12} {e.kind:<10} parent={e.causal_parent}")
    return 0


def _cmd_ledger_replay(args) -> int:
    led = _open_ledger(args.ledger)
    entries = led.replay(until=args.seq)
    print(json.dumps([dataclasses.asdict(e) for e in entries], indent=2))
    return 0


def _cmd_ledger_get(args) -> int:
    led = _open_ledger(args.ledger)
    try:
        entry = led.get(args.seq)
    except KeyError:
        print(f"no ledger entry at seq {args.seq}", file=sys.stderr)
        return 1
    print(json.dumps(dataclasses.asdict(entry), indent=2))
    return 0


def _cmd_ledger_summary(args) -> int:
    from forum.report import summarize

    s = summarize(_open_ledger(args.ledger))
    if args.json:
        print(json.dumps(s, indent=2))
        return 0
    print(f"entries: {s['entries']}")
    print(f"requests: {s['requests']} | plans: {s['plans']} | tasks: {s['tasks']}")
    print(f"task results: {s['task_results']} (failed {s['failed_results']}) | verdicts: pass {s['verdicts_pass']} / fail {s['verdicts_fail']}")
    print(f"intent checks: {s['intent_checks']} (flagged {s['intent_flagged']}, judged {s['intent_judgments']}, drift judged {s['intent_drift_judged']})")
    print(f"escalations: {s['escalations']} | budget stops: {s['budget_stops']} | contexts: {s['contexts']} | answers: {s['answers']}")
    print(f"model calls: {s['model_calls']}")
    print(f"checkpoint: {s['checkpoint'][:16]}... | verified: {s['verified']}")
    return 0


def _cmd_bench(args) -> int:
    from forum.report import compare, summarize

    a = summarize(_open_ledger(args.a))
    b = summarize(_open_ledger(args.b))
    delta = compare(a, b)
    if args.json:
        print(json.dumps({"a": a, "b": b, "delta": delta}, indent=2))
        return 0
    print(f"{'metric':<16}{'A':>8}{'B':>8}{'delta':>8}")
    for key in delta:
        print(f"{key:<16}{a.get(key, 0):>8}{b.get(key, 0):>8}{delta[key]:>+8}")
    return 0


def _add_ledger(sp) -> None:
    sp.add_argument("--ledger", default=DEFAULT_LEDGER, help="ledger directory (default: forum-ledger)")


def _add_executor(sp) -> None:
    sp.add_argument("--cmd", default=None, help='run any model command per task, e.g. --cmd "ollama run llama3" (no account needed)')
    sp.add_argument("--chat-url", default=None, help="an OpenAI-compatible chat-completions URL, e.g. a local Ollama or LM Studio server (no account needed)")
    sp.add_argument("--api", action="store_true", help="use the Anthropic API executor (reads ANTHROPIC_API_KEY)")
    sp.add_argument("--model", default=None, help="model id for --chat-url or --api")
    sp.add_argument("--api-key-env", default=None, help="env var holding a Bearer key for --chat-url (optional; local servers need none)")


def _print_help_rc(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forum", description="Forum: accountable multi-agent orchestration.")
    parser.add_argument("--version", action="version", version=f"forum {__version__}")
    sub = parser.add_subparsers(dest="command")

    route = sub.add_parser("route", help="route a request to a capability lane (no model needed)")
    route.add_argument("text")
    route.set_defaults(func=_cmd_route)

    submit = sub.add_parser("submit", help="plan and answer a request, witnessed")
    submit.add_argument("request")
    submit.add_argument("--max-model-calls", type=int, default=None, help="bound the run to N model calls (witnessed budget)")
    submit.add_argument("--max-seconds", type=float, default=None, help="bound the run to S seconds (best-effort)")
    submit.add_argument("--judge-intent", action="store_true", help="when the lexical intent floor flags drift, escalate to a model intent-judge (uses the run's executor, counts against the budget)")
    _add_ledger(submit)
    _add_executor(submit)
    submit.set_defaults(func=_cmd_submit)

    serve = sub.add_parser("serve", help="run the HTTP daemon")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    _add_ledger(serve)
    _add_executor(serve)
    serve.set_defaults(func=_cmd_serve)

    mcp = sub.add_parser("mcp", help="run the MCP (stdio) server")
    _add_ledger(mcp)
    _add_executor(mcp)
    mcp.set_defaults(func=_cmd_mcp)

    ledger = sub.add_parser("ledger", help="inspect the ledger")
    lsub = ledger.add_subparsers(dest="ledger_command")
    verify = lsub.add_parser("verify", help="verify the chain and payloads")
    _add_ledger(verify)
    verify.set_defaults(func=_cmd_ledger_verify)
    show = lsub.add_parser("show", help="list entries (seq, actor, kind)")
    _add_ledger(show)
    show.add_argument("--limit", type=int, default=0, help="show only the last N entries")
    show.set_defaults(func=_cmd_ledger_show)
    replay = lsub.add_parser("replay", help="dump entries up to a seq")
    _add_ledger(replay)
    replay.add_argument("seq", type=int)
    replay.set_defaults(func=_cmd_ledger_replay)
    get = lsub.add_parser("get", help="dump one entry by seq")
    _add_ledger(get)
    get.add_argument("seq", type=int)
    get.set_defaults(func=_cmd_ledger_get)
    summary = lsub.add_parser("summary", help="aggregate the ledger into a run summary")
    _add_ledger(summary)
    summary.add_argument("--json", action="store_true", help="emit the summary as JSON")
    summary.set_defaults(func=_cmd_ledger_summary)
    ledger.set_defaults(func=lambda a: _print_help_rc(ledger))

    bench = sub.add_parser("bench", help="compare two ledgers (A/B) by their summaries")
    bench.add_argument("a", help="ledger directory A")
    bench.add_argument("b", help="ledger directory B")
    bench.add_argument("--json", action="store_true", help="emit both summaries and the delta as JSON")
    bench.set_defaults(func=_cmd_bench)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 1
    return func(args)


if __name__ == "__main__":
    sys.exit(main())
