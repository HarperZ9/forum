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
    """Pick an executor from flags: --api or --cmd, else None (no model)."""
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
            "submit needs a model executor; pass --api (ANTHROPIC_API_KEY) "
            'or --cmd "<model cli>"',
            file=sys.stderr,
        )
        return 2
    from forum.daemon import build_orchestrator

    orch = build_orchestrator(args.ledger, executor=executor)
    try:
        answer = asyncio.run(orch.submit(args.request))
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


def _add_ledger(sp) -> None:
    sp.add_argument("--ledger", default=DEFAULT_LEDGER, help="ledger directory (default: forum-ledger)")


def _add_executor(sp) -> None:
    sp.add_argument("--api", action="store_true", help="use the Anthropic API executor (reads ANTHROPIC_API_KEY)")
    sp.add_argument("--model", default=None, help="model id for --api")
    sp.add_argument("--cmd", default=None, help='run a model CLI via subprocess, e.g. --cmd "claude -p"')


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
    ledger.set_defaults(func=lambda a: _print_help_rc(ledger))

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
