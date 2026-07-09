from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys

from forum import __version__
from forum.command_split import split_command
from forum.flagship import cmd_demo, cmd_doctor, cmd_status

DEFAULT_LEDGER = "forum-ledger"


def _command_executor(cmd: str):
    from forum.executor import SubprocessExecutor

    return SubprocessExecutor(split_command(cmd))


def _chat_executor(model: str, base_url: str, api_key_env: str | None = None):
    from forum.chat_executor import ChatExecutor

    return ChatExecutor(model, base_url=base_url, api_key_env=api_key_env)


def _make_base_executor(args):
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
        return _command_executor(cmd)
    return None


def _tier_chat_executor(args, tier: str):
    chat_url = getattr(args, f"{tier}_chat_url", None)
    if not chat_url:
        return None
    model = getattr(args, f"{tier}_model", None) or tier
    api_key_env = getattr(args, f"{tier}_api_key_env", None)
    return _chat_executor(model, chat_url, api_key_env)


def _tier_executors(args) -> dict:
    commands = {
        "cheap": getattr(args, "cheap_cmd", None),
        "capable": getattr(args, "capable_cmd", None),
        "frontier": getattr(args, "frontier_cmd", None),
    }
    tiers = {}
    for tier, cmd in commands.items():
        chat = _tier_chat_executor(args, tier)
        if chat is not None:
            tiers[tier] = chat
        elif cmd:
            tiers[tier] = _command_executor(cmd)
    return tiers


def _config_executors(args):
    path = getattr(args, "runtime_config", None)
    if not path:
        return None, {}
    from forum.runtime_config import executors_from_runtime_config

    return executors_from_runtime_config(path)


def _runtime_descriptors(args):
    from forum.runtime_descriptor import (
        cli_default_descriptor,
        cli_tier_descriptors,
        descriptor_from_config,
    )

    config_base, config_tiers = (None, {})
    path = getattr(args, "runtime_config", None)
    if path:
        config_base, config_tiers = descriptor_from_config(path)
    base = cli_default_descriptor(args) or config_base
    tiers = {**config_tiers, **cli_tier_descriptors(args)}
    return base, tiers


def _default_executor(base, tiers: dict):
    if base is not None:
        return base
    for tier in ("capable", "frontier", "cheap"):
        if tier in tiers:
            return tiers[tier]
    return None


def _make_executor(args):
    config_base, config_tiers = _config_executors(args)
    base = _make_base_executor(args) or config_base
    tiers = {**config_tiers, **_tier_executors(args)}
    if not tiers:
        return base
    from forum.roster import load_default
    from forum.runtime import TieredExecutor

    return TieredExecutor(load_default(), _default_executor(base, tiers), tiers=tiers)


def _make_executor_or_error(args):
    try:
        return _make_executor(args), None
    except ValueError as exc:
        return None, f"invalid runtime config: {exc}"


def _runtime_descriptors_or_error(args):
    try:
        return (*_runtime_descriptors(args), None)
    except ValueError as exc:
        return None, {}, f"invalid runtime config: {exc}"


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

def _cmd_import_trace(args) -> int:
    import sys as _sys

    from forum.flight_recorder import TraceParseError, import_trace

    try:
        text = _sys.stdin.read() if args.trace == "-" else open(args.trace, encoding="utf-8").read()
        events = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"import-trace: cannot read trace: {exc}", file=_sys.stderr)
        return 2
    try:
        record = import_trace(events, args.format)
    except TraceParseError as exc:
        print(f"import-trace: {exc}", file=_sys.stderr)
        return 2
    print(json.dumps(record, indent=2))
    return 0


def _cmd_grade(args) -> int:
    from forum.grade import grade_ledger

    led = _open_ledger(args.ledger)
    print(json.dumps(grade_ledger(led, min_checks=args.min_checks), indent=2))
    return 0


def _cmd_export_gradable(args) -> int:
    from forum.gradable_export import gradable_record, write_gradable_jsonl

    led = _open_ledger(args.ledger)
    row = gradable_record(led, min_checks=args.min_checks)
    if args.out:
        write_gradable_jsonl([row], args.out)
        print(f"wrote 1 gradable-trajectory row -> {args.out} "
              f"(grade={row['grade']['label']} reward={row['grade']['reward']})")
    else:
        print(json.dumps(row, indent=2))
    return 0


def _cmd_mine(args) -> int:
    """One command: fold ANY framework's trace into a verifiable ledger, grade it,
    and append it as a gradable-trajectory datum. trace -> witnessed RL data."""
    import sys as _sys

    from forum.flight_recorder import TraceParseError, ledger_from_trace
    from forum.gradable_export import gradable_record, write_gradable_jsonl

    try:
        text = _sys.stdin.read() if args.trace == "-" else open(args.trace, encoding="utf-8").read()
        events = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"mine: cannot read trace: {exc}", file=_sys.stderr)
        return 2
    try:
        led, _ = ledger_from_trace(events, args.format)
    except TraceParseError as exc:
        print(f"mine: {exc}", file=_sys.stderr)
        return 2
    row = gradable_record(led, min_checks=args.min_checks)
    if args.out:
        write_gradable_jsonl([row], args.out)
        print(f"mined {args.trace} -> {args.out} "
              f"(grade={row['grade']['label']} reward={row['grade']['reward']}, "
              f"merkle={row['oracle']['merkle_root'][:12]}...)")
    else:
        print(json.dumps(row, indent=2))
    return 0


def _cmd_route(args) -> int:
    from forum.roster import load_default
    from forum.route_frame import derive_route_frame, frame_payload
    from forum.routing import LexicalRouter

    roster = load_default()
    result = LexicalRouter().score(args.text, roster)
    frame = derive_route_frame(args.text, result, roster)
    print(json.dumps({
        "decided": result.decided,
        "confidence": result.confidence,
        "needs_escalation": result.needs_escalation,
        "candidates": [{"agent": c.agent, "score": c.score} for c in result.candidates],
        "frame": frame_payload(frame),
    }, indent=2))
    return 0


def _cmd_submit(args) -> int:
    executor, executor_error = _make_executor_or_error(args)
    if executor_error is not None:
        print(executor_error, file=sys.stderr)
        return 2
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
                checkpoint_each_wave=args.checkpoint_each_wave,
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

    executor, executor_error = _make_executor_or_error(args)
    if executor_error is not None:
        print(executor_error, file=sys.stderr)
        return 2
    asyncio.run(serve(
        ledger_dir=args.ledger, host=args.host, port=args.port, executor=executor
    ))
    return 0


def _cmd_mcp(args) -> int:
    from forum.daemon import build_orchestrator
    from forum.mcp_surface import serve_stdio

    executor, executor_error = _make_executor_or_error(args)
    if executor_error is not None:
        print(executor_error, file=sys.stderr)
        return 2
    orch = build_orchestrator(args.ledger, executor=executor)
    asyncio.run(serve_stdio(orch))
    return 0


def _cmd_context_preflight(args) -> int:
    from forum.context_preflight import build_context_preflight, context_preflight_text

    try:
        budget, _ = _make_context_budget(args)
    except ValueError as exc:
        print(f"invalid context budget: {exc}", file=sys.stderr)
        return 2
    context = ""
    context_source = "none"
    if args.use_capsule_context:
        from forum.context_capsule import build_context_capsule, capsule_text

        capsule = build_context_capsule(
            _open_ledger(args.ledger),
            max_items=args.max_items,
            max_text_chars=args.max_text_chars,
        )
        context = capsule_text(capsule)
        context_source = "capsule"
    payload = build_context_preflight(
        args.request,
        context=context,
        context_source=context_source,
        budget=budget,
    )
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(context_preflight_text(payload))
    return 0


def _cmd_runtime_inspect(args) -> int:
    from forum.roster import load_default
    from forum.runtime_inspect import inspect_runtime, runtime_inspect_text

    default, tiers, descriptor_error = _runtime_descriptors_or_error(args)
    if descriptor_error is not None:
        print(descriptor_error, file=sys.stderr)
        return 2
    payload = inspect_runtime(default, tiers, load_default())
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(runtime_inspect_text(payload))
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


def _cmd_ledger_room(args) -> int:
    from forum.run_room import build_run_room, room_brief_text, room_text

    room = build_run_room(
        _open_ledger(args.ledger),
        max_text_chars=args.max_text_chars,
    )
    if args.brief:
        print(room_brief_text(room))
        return 0
    if args.text:
        print(room_text(room))
        return 0
    print(json.dumps(room, indent=2))
    return 0


def _pending_gates(led) -> list[dict]:
    """Unresolved gate_pending entries in the ledger, newest last."""
    from forum.gates import gate_resolution

    pending: list[dict] = []
    for entry in led.query(kind="gate_pending"):
        body = led.get_payload(entry.payload_hash)
        run_seq = body.get("run_seq")
        wave = body.get("wave")
        if gate_resolution(led, run_seq, wave) == "pending":
            item = {
                "seq": entry.seq,
                "run_seq": run_seq,
                "wave": wave,
                "tasks": list(body.get("tasks") or []),
                "question": body.get("question", ""),
            }
            deadline = body.get("deadline")
            if isinstance(deadline, (int, float)):
                # A bounded gate: surface its deadline and the auto-decision that
                # fires on resume if it lapses, so the operator sees the clock.
                item["deadline"] = float(deadline)
                item["on_expiry"] = str(body.get("on_expiry") or "reject")
            pending.append(item)
    return pending


def _cmd_gate_list(args) -> int:
    led = _open_ledger(args.ledger)
    pending = _pending_gates(led)
    if args.json:
        print(json.dumps({"pending": pending}, indent=2))
        return 0
    if not pending:
        print("no pending gates")
        return 0
    for gate in pending:
        line = f"run_seq={gate['run_seq']} wave={gate['wave']} tasks={gate['tasks']}: {gate['question']}"
        if "deadline" in gate:
            line += f" [deadline={gate['deadline']:.0f} on_expiry={gate['on_expiry']}]"
        print(line)
    return 0


def _parse_edits(pairs) -> tuple[dict, str | None]:
    edits: dict[str, str] = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            return {}, f"invalid --edit {pair!r}; expected TASK_ID=INSTRUCTION"
        edits[key] = value
    return edits, None


def _cmd_gate_resolve(args, kind: str) -> int:
    from forum.gates import resolve_gate

    led = _open_ledger(args.ledger)
    edits: dict[str, str] = {}
    if kind == "gate_edited":
        edits, edit_error = _parse_edits(getattr(args, "edit", None))
        if edit_error is not None:
            print(edit_error, file=sys.stderr)
            return 2
        if not edits:
            print("gate edit needs at least one --edit TASK_ID=INSTRUCTION", file=sys.stderr)
            return 2
    entry = resolve_gate(
        led, args.run_seq, args.wave, kind,
        approver=args.approver,
        note=getattr(args, "note", "") or "",
        reason=getattr(args, "reason", "") or "",
        edits=edits,
    )
    print(json.dumps({"resolved": kind, "seq": entry.seq, "run_seq": args.run_seq, "wave": args.wave}))
    return 0


def _cmd_campaign_declare(args) -> int:
    from forum.campaign import campaign_from_payload, declare_campaign

    try:
        with open(args.file, encoding="utf-8") as fh:
            body = json.load(fh)
    except (OSError, ValueError) as exc:
        print(f"cannot read campaign file: {exc}", file=sys.stderr)
        return 2
    try:
        campaign = campaign_from_payload(body)
    except (KeyError, TypeError, ValueError) as exc:
        print(f"invalid campaign file: {exc}", file=sys.stderr)
        return 2
    led = _open_ledger(args.ledger)
    try:
        entry = declare_campaign(led, campaign)
    except ValueError as exc:
        print(f"campaign rejected: {exc}", file=sys.stderr)
        return 1
    led.sync()
    print(json.dumps({"declared": campaign.campaign_id, "seq": entry.seq}))
    return 0


def _cmd_campaign_status(args) -> int:
    from forum.campaign_room import build_campaign_room, campaign_room_text

    led = _open_ledger(args.ledger)
    try:
        room = build_campaign_room(led, args.campaign_id)
    except KeyError:
        print(f"no campaign {args.campaign_id!r} in this ledger", file=sys.stderr)
        return 1
    if args.text:
        print(campaign_room_text(room))
        return 0
    print(json.dumps(room, indent=2))
    return 0


def _cmd_campaign_next(args) -> int:
    from forum.campaign_room import derive_campaign_next_actions
    from forum.campaign_status import derive_campaign_status

    led = _open_ledger(args.ledger)
    try:
        status = derive_campaign_status(led, args.campaign_id)
    except KeyError:
        print(f"no campaign {args.campaign_id!r} in this ledger", file=sys.stderr)
        return 1
    actions = derive_campaign_next_actions(status)
    print(json.dumps({"next_actions": actions}, indent=2))
    return 0


def _cmd_campaign_ingest_status(args) -> int:
    from forum.campaign_ingest import ingest_feature_status, ingest_project_status

    led = _open_ledger(args.ledger)
    if args.feature:
        entry = ingest_feature_status(
            led, args.campaign_id, args.project, args.feature, args.status,
            source=args.source, reason=args.reason or "",
        )
    else:
        entry = ingest_project_status(
            led, args.campaign_id, args.project, args.status,
            source=args.source, reason=args.reason or "",
        )
    led.sync()
    print(json.dumps({"ingested": entry.kind, "seq": entry.seq}))
    return 0


def _cmd_campaign_run(args) -> int:
    from forum.campaign import campaign_from_payload
    from forum.campaign_dispatch import run_campaign
    from forum.campaign_room import build_campaign_room
    from forum.campaign_status import load_declared_campaign

    executor, executor_error = _make_executor_or_error(args)
    if executor_error is not None:
        print(executor_error, file=sys.stderr)
        return 2
    if executor is None:
        print(
            "campaign run needs a model executor. Forum is model-agnostic: pass --cmd "
            '"<model cli>", --chat-url <openai-compatible url>, or --api (Anthropic).',
            file=sys.stderr,
        )
        return 2
    led = _open_ledger(args.ledger)
    declared = load_declared_campaign(led, args.campaign_id)
    if declared is None:
        print(f"no campaign {args.campaign_id!r} in this ledger", file=sys.stderr)
        return 1
    campaign = campaign_from_payload(declared)
    asyncio.run(run_campaign(led, campaign, executor, max_parallel=args.max_parallel))
    room = build_campaign_room(led, args.campaign_id)
    if args.json:
        print(json.dumps(room, indent=2))
        return 0
    print(json.dumps({
        "campaign_id": room["campaign_id"],
        "complete": room["complete"],
        "progress": room["progress"],
    }, indent=2))
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


def _cmd_bench_deep_verify(args) -> int:
    from forum.bench_deep_verify import (
        benchmark_matrix,
        dumps,
        parse_float_csv,
        parse_int_csv,
        report_text,
    )

    try:
        payload = benchmark_matrix(
            entry_counts=parse_int_csv(args.entries),
            payload_body_bytes=parse_int_csv(args.payload_bytes),
            storage_modes=args.storage or ["memory"],
            redaction_ratios=parse_float_csv(args.redaction_ratio),
            repeats=args.repeats,
            warmups=args.warmups,
        )
    except ValueError as exc:
        print(f"bench-deep-verify: {exc}", file=sys.stderr)
        return 2
    text = dumps(payload)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text if args.json else report_text(payload))
    return 0


def _add_ledger(sp) -> None:
    sp.add_argument("--ledger", default=DEFAULT_LEDGER, help="ledger directory (default: forum-ledger)")


def _add_executor(sp) -> None:
    sp.add_argument("--runtime-config", default=None, help="local TOML runtime config for default and tier executors")
    sp.add_argument("--cmd", default=None, help='run any model command per task, e.g. --cmd "ollama run llama3" (no account needed)')
    sp.add_argument("--cheap-cmd", default=None, help="command for cheap roster-tier task agents")
    sp.add_argument("--capable-cmd", default=None, help="command for capable roster-tier task agents")
    sp.add_argument("--frontier-cmd", default=None, help="command for frontier roster-tier task agents")
    sp.add_argument("--cheap-chat-url", default=None, help="OpenAI-compatible chat-completions URL for cheap roster-tier task agents")
    sp.add_argument("--cheap-model", default=None, help="model id for --cheap-chat-url")
    sp.add_argument("--cheap-api-key-env", default=None, help="env var holding a Bearer key for --cheap-chat-url")
    sp.add_argument("--capable-chat-url", default=None, help="OpenAI-compatible chat-completions URL for capable roster-tier task agents")
    sp.add_argument("--capable-model", default=None, help="model id for --capable-chat-url")
    sp.add_argument("--capable-api-key-env", default=None, help="env var holding a Bearer key for --capable-chat-url")
    sp.add_argument("--frontier-chat-url", default=None, help="OpenAI-compatible chat-completions URL for frontier roster-tier task agents")
    sp.add_argument("--frontier-model", default=None, help="model id for --frontier-chat-url")
    sp.add_argument("--frontier-api-key-env", default=None, help="env var holding a Bearer key for --frontier-chat-url")
    sp.add_argument("--chat-url", default=None, help="an OpenAI-compatible chat-completions URL, e.g. a local Ollama or LM Studio server (no account needed)")
    sp.add_argument("--api", action="store_true", help="use the Anthropic API executor (reads ANTHROPIC_API_KEY)")
    sp.add_argument("--model", default=None, help="model id for --chat-url or --api")
    sp.add_argument("--api-key-env", default=None, help="env var holding a Bearer key for --chat-url (optional; local servers need none)")


def _add_context_budget(sp) -> None:
    sp.add_argument("--context-token-budget", type=int, default=None, help="bound admitted context across the run to N approximate tokens")
    sp.add_argument("--request-context-token-budget", type=int, default=None, help="bound request-level context to N approximate tokens")
    sp.add_argument("--task-context-token-budget", type=int, default=None, help="bound each per-task context slice to N approximate tokens")
    sp.add_argument("--upstream-token-budget", type=int, default=None, help="bound each upstream result injection to N approximate tokens")


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

    ft = sub.add_parser(
        "import-trace",
        help="fold an external agent trace (LangSmith/OTel/AgentOps/generic JSON) "
             "into a verifiable, replayable ledger — a flight recorder that "
             "refutes its own tampering")
    ft.add_argument("trace", help="path to a JSON trace (list of events), or - for stdin")
    ft.add_argument("--format", choices=["langsmith", "otel", "agentops", "generic"],
                    default="generic")
    ft.set_defaults(func=_cmd_import_trace)

    grade = sub.add_parser(
        "grade",
        help="grade a run's ledger — an outcome signal that CAN fail and counts "
             "only independent checks (a producer cannot grade itself)")
    grade.add_argument("ledger", help="path to a persisted ledger directory")
    grade.add_argument("--min-checks", type=int, default=2)
    grade.set_defaults(func=_cmd_grade)

    exp = sub.add_parser(
        "export-gradable",
        help="export a run's ledger as one forum.gradable-trajectory/1 datum "
             "(prompt + trajectory + a can-fail grade + off-forum re-derivation inputs)")
    exp.add_argument("ledger", help="path to a persisted ledger directory")
    exp.add_argument("--out", help="append the sealed row to this JSONL (else print)")
    exp.add_argument("--min-checks", type=int, default=2)
    exp.set_defaults(func=_cmd_export_gradable)

    mine = sub.add_parser(
        "mine",
        help="one command: fold ANY framework's trace into a verifiable ledger, "
             "grade it, and append it as witnessed gradable RL data")
    mine.add_argument("trace", help="path to a JSON trace (list of events), or - for stdin")
    mine.add_argument("--format", choices=["langsmith", "otel", "agentops", "generic"],
                      default="generic")
    mine.add_argument("--out", help="append the sealed gradable row to this JSONL (else print)")
    mine.add_argument("--min-checks", type=int, default=2)
    mine.set_defaults(func=_cmd_mine)

    submit = sub.add_parser("submit", help="plan and answer a request, witnessed")
    submit.add_argument("request")
    submit.add_argument("--max-model-calls", type=int, default=None, help="bound the run to N model calls (witnessed budget)")
    submit.add_argument("--max-seconds", type=float, default=None, help="bound the run to S seconds (best-effort)")
    _add_context_budget(submit)
    submit.add_argument("--use-capsule-context", action="store_true", help="feed the current ledger's context capsule into the run before planning")
    submit.add_argument("--delivery-profile", default=None, help="delivery profile to witness: operator, engineer, researcher, executive")
    submit.add_argument("--checkpoint-each-wave", action="store_true", help="witness a checkpoint after each execution wave")
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

    context = sub.add_parser("context", help="inspect and preflight context pressure")
    csub = context.add_subparsers(dest="context_command")
    preflight = csub.add_parser("preflight", help="estimate request and capsule context pressure")
    preflight.add_argument("request")
    preflight.add_argument("--json", action="store_true", help="emit context preflight as JSON")
    preflight.add_argument("--use-capsule-context", action="store_true", help="include the current ledger capsule in the preflight")
    preflight.add_argument("--max-items", type=int, default=8, help="maximum capsule task result items to include")
    preflight.add_argument("--max-text-chars", type=int, default=240, help="maximum capsule characters copied from any text field")
    _add_ledger(preflight)
    _add_context_budget(preflight)
    preflight.set_defaults(func=_cmd_context_preflight)
    context.set_defaults(func=lambda a: _print_help_rc(context))

    runtime = sub.add_parser("runtime", help="inspect runtime executor policy")
    rsub = runtime.add_subparsers(dest="runtime_command")
    inspect = rsub.add_parser("inspect", help="explain default and tier executors")
    inspect.add_argument("--json", action="store_true", help="emit runtime inspection as JSON")
    _add_executor(inspect)
    inspect.set_defaults(func=_cmd_runtime_inspect)
    runtime.set_defaults(func=lambda a: _print_help_rc(runtime))

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
    room = lsub.add_parser("room", help="project the latest run into an operator room snapshot")
    _add_ledger(room)
    room.add_argument("--json", action="store_true", help="emit the run room as JSON (default)")
    room.add_argument("--brief", action="store_true", help="emit the polished operator brief")
    room.add_argument("--text", action="store_true", help="emit prompt-safe room text")
    room.add_argument("--max-text-chars", type=int, default=240, help="maximum characters copied from any text field")
    room.set_defaults(func=_cmd_ledger_room)
    ledger.set_defaults(func=lambda a: _print_help_rc(ledger))

    gate = sub.add_parser("gate", help="list and resolve human-in-the-loop approval gates")
    gsub = gate.add_subparsers(dest="gate_command")
    gate_list = gsub.add_parser("list", help="list pending (unresolved) gates")
    _add_ledger(gate_list)
    gate_list.add_argument("--json", action="store_true", help="emit pending gates as JSON")
    gate_list.set_defaults(func=_cmd_gate_list)
    gate_approve = gsub.add_parser("approve", help="approve a pending gate so its wave runs on resume")
    _add_ledger(gate_approve)
    gate_approve.add_argument("--run-seq", type=int, required=True, help="the plan (run) seq the gate belongs to")
    gate_approve.add_argument("--wave", type=int, required=True, help="the gated wave index")
    gate_approve.add_argument("--approver", required=True, help="who approved (witnessed)")
    gate_approve.add_argument("--note", default="", help="optional approval note")
    gate_approve.set_defaults(func=lambda a: _cmd_gate_resolve(a, "gate_approved"))
    gate_edit = gsub.add_parser("edit", help="approve a gate and rewrite its tasks' instructions")
    _add_ledger(gate_edit)
    gate_edit.add_argument("--run-seq", type=int, required=True, help="the plan (run) seq the gate belongs to")
    gate_edit.add_argument("--wave", type=int, required=True, help="the gated wave index")
    gate_edit.add_argument("--approver", required=True, help="who approved (witnessed)")
    gate_edit.add_argument("--edit", action="append", help="TASK_ID=INSTRUCTION replacement (repeatable)")
    gate_edit.add_argument("--note", default="", help="optional edit note")
    gate_edit.set_defaults(func=lambda a: _cmd_gate_resolve(a, "gate_edited"))
    gate_reject = gsub.add_parser("reject", help="reject a pending gate so its wave never runs")
    _add_ledger(gate_reject)
    gate_reject.add_argument("--run-seq", type=int, required=True, help="the plan (run) seq the gate belongs to")
    gate_reject.add_argument("--wave", type=int, required=True, help="the gated wave index")
    gate_reject.add_argument("--approver", required=True, help="who rejected (witnessed)")
    gate_reject.add_argument("--reason", default="", help="why the wave was rejected")
    gate_reject.set_defaults(func=lambda a: _cmd_gate_resolve(a, "gate_rejected"))
    gate.set_defaults(func=lambda a: _print_help_rc(gate))

    campaign = sub.add_parser("campaign", help="declare, inspect, and run a witnessed multi-project campaign")
    camp_sub = campaign.add_subparsers(dest="campaign_command")
    camp_declare = camp_sub.add_parser("declare", help="declare a campaign from a JSON file (witnessed once)")
    camp_declare.add_argument("--file", required=True, help="path to a campaign JSON file")
    _add_ledger(camp_declare)
    camp_declare.set_defaults(func=_cmd_campaign_declare)
    camp_status = camp_sub.add_parser("status", help="reduce the ledger into a campaign's current status")
    camp_status.add_argument("--campaign-id", required=True, help="the campaign id to reduce")
    camp_status.add_argument("--json", action="store_true", help="emit the campaign room as JSON (default)")
    camp_status.add_argument("--text", action="store_true", help="emit prompt-safe room text")
    _add_ledger(camp_status)
    camp_status.set_defaults(func=_cmd_campaign_status)
    camp_next = camp_sub.add_parser("next", help="derive the campaign's next operator actions")
    camp_next.add_argument("--campaign-id", required=True, help="the campaign id")
    camp_next.add_argument("--json", action="store_true", help="emit next actions as JSON (default)")
    _add_ledger(camp_next)
    camp_next.set_defaults(func=_cmd_campaign_next)
    camp_run = camp_sub.add_parser("run", help="best-effort dispatch of a campaign's runnable forum features to a fixed point")
    camp_run.add_argument("--campaign-id", required=True, help="the campaign id to run")
    camp_run.add_argument("--max-parallel", type=int, default=6, help="max features dispatched concurrently per wave")
    camp_run.add_argument("--json", action="store_true", help="emit the full campaign room as JSON")
    _add_ledger(camp_run)
    _add_executor(camp_run)
    camp_run.set_defaults(func=_cmd_campaign_run)
    camp_ingest = camp_sub.add_parser("ingest-status", help="record an external project's or feature's status (no execution)")
    camp_ingest.add_argument("--campaign-id", required=True, help="the campaign id")
    camp_ingest.add_argument("--project", required=True, help="the project id the status belongs to")
    camp_ingest.add_argument("--feature", default=None, help="a feature id (omit to record project-level status)")
    camp_ingest.add_argument("--status", required=True, help="the reported status (done/in_progress/blocked/failed)")
    camp_ingest.add_argument("--source", required=True, help="the reporting system, e.g. external:telos")
    camp_ingest.add_argument("--reason", default="", help="optional reason/context for the status")
    _add_ledger(camp_ingest)
    camp_ingest.set_defaults(func=_cmd_campaign_ingest_status)
    campaign.set_defaults(func=lambda a: _print_help_rc(campaign))

    bench = sub.add_parser("bench", help="compare two ledgers (A/B) by their summaries")
    bench.add_argument("a", help="ledger directory A")
    bench.add_argument("b", help="ledger directory B")
    bench.add_argument("--json", action="store_true", help="emit both summaries and the delta as JSON")
    bench.set_defaults(func=_cmd_bench)

    deep = sub.add_parser(
        "bench-deep-verify",
        help="measure ledger verify(deep=True) scaling across payload and storage variables",
    )
    deep.add_argument("--entries", default="100,1000", help="comma-separated entry counts")
    deep.add_argument("--payload-bytes", default="256,4096", help="comma-separated body byte targets")
    deep.add_argument(
        "--storage",
        action="append",
        choices=["memory", "file-sync", "file-batched"],
        default=None,
        help="storage mode to include; repeat for multiple modes",
    )
    deep.add_argument(
        "--redaction-ratio",
        default="0,0.5,1",
        help="comma-separated ratios of payload bodies removed before verification",
    )
    deep.add_argument("--warmups", type=int, default=1, help="warmup iterations per case")
    deep.add_argument("--repeats", type=int, default=5, help="measured iterations per case")
    deep.add_argument("--json", action="store_true", help="emit the full JSON payload")
    deep.add_argument("--out", default=None, help="write the full JSON payload to this path")
    deep.set_defaults(func=_cmd_bench_deep_verify)

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
