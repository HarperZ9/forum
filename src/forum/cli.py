from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import shlex
import sys

from forum import __version__
from forum.flagship import cmd_demo, cmd_doctor, cmd_status

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

        return SubprocessExecutor(shlex.split(cmd, posix=os.name != "nt"))
    return None


def _open_ledger(directory):
    from forum.ledger import Ledger
    from forum.storage import FileStorage

    return Ledger(FileStorage(directory))


def _make_context_budget(args):
    values = {
        "max_total_tokens": getattr(args, "context_token_budget", None),
        "max_request_tokens": getattr(args, "request_context_token_budget", None),
        "max_task_tokens": getattr(args, "task_context_token_budget", None),
        "max_upstream_tokens": getattr(args, "upstream_token_budget", None),
    }
    if all(value is None for value in values.values()):
        return None, {}
    from forum.context_budget import ContextBudget

    budget = ContextBudget(**values)
    return budget, budget.configured_limits()



def _cmd_humanize(args) -> int:
    from forum.humanize import humanize_text

    try:
        print(json.dumps(humanize_text(args.text, audience=args.audience, profile=args.profile)))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0

def _cmd_route(args) -> int:
    from forum.route_frame import derive_route_frame, frame_payload
    from forum.roster import load_default
    from forum.routing import LexicalRouter

    result = LexicalRouter().score(args.text, load_default())
    frame = derive_route_frame(args.text, result)
    print(json.dumps({
        "decided": result.decided,
        "confidence": result.confidence,
        "needs_escalation": result.needs_escalation,
        "candidates": [{"agent": c.agent, "score": c.score} for c in result.candidates],
        "frame": frame_payload(frame),
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
    from forum.receipts import submit_receipt

    budget = None
    budget_payload = {}
    if args.max_model_calls is not None or args.max_seconds is not None:
        budget = RunBudget(max_model_calls=args.max_model_calls, max_seconds=args.max_seconds)
        if args.max_model_calls is not None:
            budget_payload["max_model_calls"] = args.max_model_calls
        if args.max_seconds is not None:
            budget_payload["max_seconds"] = args.max_seconds
    try:
        context_budget, context_budget_payload = _make_context_budget(args)
    except ValueError as exc:
        print(f"invalid context budget: {exc}", file=sys.stderr)
        return 2
    intent_judge = None
    if getattr(args, "judge_intent", False):
        from forum.control import IntentJudge

        intent_judge = IntentJudge()
    orch = build_orchestrator(args.ledger, executor=executor, intent_judge=intent_judge)
    if args.use_capsule_context:
        from forum.context_capsule import LedgerCapsuleProvider

        orch.context_provider = LedgerCapsuleProvider(orch.ledger)
    before_seq = orch.ledger.count()
    try:
        answer = asyncio.run(
            orch.submit(
                args.request,
                budget=budget,
                context_budget=context_budget,
                delivery_profile=args.delivery_profile,
            )
        )
    except ValueError as exc:
        print(f"submit failed: {exc}", file=sys.stderr)
        return 1
    checkpoint = orch.ledger.checkpoint()
    receipt = submit_receipt(
        orch.ledger,
        before_seq=before_seq,
        request=args.request,
        answer=answer,
        executor=executor,
        budget=budget_payload,
        context_budget=context_budget_payload,
        delivery_profile=args.delivery_profile,
    )
    if args.json:
        print(json.dumps({"answer": answer, "checkpoint": checkpoint, "receipt": receipt}, indent=2))
        return 0
    print(answer)
    print(f"checkpoint: {checkpoint}", file=sys.stderr)
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
    print(f"verifications: {s['verifications']} (refuted {s['verifications_refuted']})")
    print(f"delivery checks: {s['delivery_checks']} (flagged {s['delivery_flagged']}) | revisions: {s['revisions']} (accepted {s['revisions_accepted']})")
    print(f"escalations: {s['escalations']} | budget stops: {s['budget_stops']} | contexts: {s['contexts']} | answers: {s['answers']}")
    print(f"checkpoints: {s['checkpoints']} | resumes: {s['resumes']} | payload weight: {s['payload_bytes']} bytes")
    print(f"model calls: {s['model_calls']}")
    print(f"checkpoint: {s['checkpoint'][:16]}... | verified: {s['verified']}")
    return 0


def _cmd_ledger_capsule(args) -> int:
    from forum.context_capsule import build_context_capsule, capsule_text

    capsule = build_context_capsule(
        _open_ledger(args.ledger),
        max_items=args.max_items,
        max_text_chars=args.max_text_chars,
    )
    if args.text:
        print(capsule_text(capsule))
        return 0
    print(json.dumps(capsule, indent=2))
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

    status = sub.add_parser("status", help="emit Forum's Project Telos operator-spine status")
    status.add_argument("--json", action="store_true", help="emit a Project Telos action envelope")
    status.set_defaults(func=cmd_status)

    doctor = sub.add_parser("doctor", help="check Forum's operator-spine readiness")
    doctor.add_argument("--json", action="store_true", help="emit a Project Telos action envelope")
    doctor.set_defaults(func=cmd_doctor)

    demo = sub.add_parser("demo", help="show Forum's operator-spine demo command")
    demo.add_argument("--json", action="store_true", help="emit a Project Telos action envelope")
    demo.set_defaults(func=cmd_demo)


    humanize = sub.add_parser("humanize", help="clarify model or agent prose without adding facts")
    humanize.add_argument("text")
    humanize.add_argument("--audience", default="operator")
    humanize.add_argument(
        "--profile",
        default=None,
        help="delivery profile to assess: operator, engineer, researcher, executive",
    )
    humanize.set_defaults(func=_cmd_humanize)

    route = sub.add_parser("route", help="route a request to a capability lane (no model needed)")
    route.add_argument("text")
    route.add_argument(
        "--json",
        action="store_true",
        help="accepted for operator-surface consistency; route already emits JSON",
    )
    route.set_defaults(func=_cmd_route)

    submit = sub.add_parser("submit", help="plan and answer a request, witnessed")
    submit.add_argument("request")
    submit.add_argument("--max-model-calls", type=int, default=None, help="bound the run to N model calls (witnessed budget)")
    submit.add_argument("--max-seconds", type=float, default=None, help="bound the run to S seconds (best-effort)")
    submit.add_argument("--context-token-budget", type=int, default=None, help="bound admitted context across the run to N approximate tokens")
    submit.add_argument("--request-context-token-budget", type=int, default=None, help="bound request-level context to N approximate tokens")
    submit.add_argument("--task-context-token-budget", type=int, default=None, help="bound each per-task context slice to N approximate tokens")
    submit.add_argument("--upstream-token-budget", type=int, default=None, help="bound each upstream result injection to N approximate tokens")
    submit.add_argument("--use-capsule-context", action="store_true", help="feed the current ledger's context capsule into the run before planning")
    submit.add_argument("--delivery-profile", default=None, help="delivery profile to witness: operator, engineer, researcher, executive")
    submit.add_argument("--judge-intent", action="store_true", help="when the lexical intent floor flags drift, escalate to a model intent-judge (uses the run's executor, counts against the budget)")
    submit.add_argument("--json", action="store_true", help="emit answer, checkpoint, and Project Telos action receipt as JSON")
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
    capsule = lsub.add_parser("capsule", help="compact the ledger into a reusable context capsule")
    _add_ledger(capsule)
    capsule.add_argument("--json", action="store_true", help="emit the capsule as JSON (default)")
    capsule.add_argument("--text", action="store_true", help="emit prompt-safe capsule text")
    capsule.add_argument("--max-items", type=int, default=8, help="maximum task result items to include")
    capsule.add_argument("--max-text-chars", type=int, default=240, help="maximum characters copied from any text field")
    capsule.set_defaults(func=_cmd_ledger_capsule)
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
