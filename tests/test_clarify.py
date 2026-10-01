import json
import shutil
import socket
import sys
import types

import pytest

from forum import clarify_articulate
from forum._vendor import safe_spawn
from forum.clarify import CLARIFY_SCHEMA, clarify_text

STIFF = ("As an AI language model, it is important to note that in order to utilize this "
         "methodology, the system should provide assistance prior to deployment")
CLEAN = "To use this method, the system should help before deployment."
DASHED = "Prior to release 2.1 — the final one — utilize the report"


@pytest.fixture
def auto_engine(monkeypatch):
    monkeypatch.delenv("FORUM_CLARIFY_ENGINE", raising=False)


@pytest.fixture
def no_articulate_package(monkeypatch):
    monkeypatch.setitem(sys.modules, "articulate", None)
    monkeypatch.setitem(sys.modules, "articulate.host_edit", None)


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("clarify opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def _fake_articulate(monkeypatch, *, refuse=False):
    """A stand-in Articulate package: replaces em dashes, guards numbers."""
    calls = []
    host_edit = types.ModuleType("articulate.host_edit")

    def deterministic_edit(text, profile=None, **kw):
        calls.append(("deterministic_edit", profile))
        return {"ok": True, "text": text.replace(" — ", ", ")}

    def edit_plan(text, goal="fix", profile=None, **kw):
        calls.append(("edit_plan", goal, profile))
        return {"ok": True, "plan_id": "plan-1"}

    def edit_submit(text, rewrite, plan_id, **kw):
        calls.append(("edit_submit", plan_id))
        accepted = text if refuse else rewrite
        refused = [{"paragraph": 0, "reasons": ["number protected spans changed"]}] if refuse else []
        return {"ok": True, "text": accepted, "gate_before": "blocked", "gate_after": "ok",
                "refused": refused, "remaining_findings": [{"rule_id": "r/one"}],
                "receipt": {"schema": "articulate/editor-receipt/v1", "backend": "host"}}

    host_edit.deterministic_edit = deterministic_edit
    host_edit.edit_plan = edit_plan
    host_edit.edit_submit = edit_submit
    package = types.ModuleType("articulate")
    package.__version__ = "9.9.9"
    package.host_edit = host_edit
    monkeypatch.setitem(sys.modules, "articulate", package)
    monkeypatch.setitem(sys.modules, "articulate.host_edit", host_edit)
    return calls


def test_builtin_engine_keeps_the_fixed_rules():
    payload = clarify_text(STIFF, engine="forum-builtin")
    assert payload["schema"] == CLARIFY_SCHEMA == "forum.prose-clarification/v1"
    assert payload["engine"] == "forum-builtin"
    assert payload["output"] == CLEAN
    assert {"removed model preamble", "simplified phrasing"} <= set(payload["edits"])
    assert payload["not_verified"] == ["facts were not independently checked"]
    assert "articulate" not in payload


def test_engine_env_var_selects_builtin(monkeypatch):
    _fake_articulate(monkeypatch)
    monkeypatch.setenv("FORUM_CLARIFY_ENGINE", "forum-builtin")
    assert clarify_text(STIFF)["engine"] == "forum-builtin"


def test_unknown_engine_is_rejected():
    with pytest.raises(ValueError, match="unknown clarify engine"):
        clarify_text(STIFF, engine="gpt")


def test_empty_text_is_rejected():
    with pytest.raises(ValueError, match="non-empty"):
        clarify_text("   ")


def test_auto_hands_off_to_importable_articulate(monkeypatch, auto_engine):
    calls = _fake_articulate(monkeypatch)
    payload = clarify_text(DASHED)
    assert payload["engine"] == "articulate"
    assert payload["output"] == "Before release 2.1, the final one, use the report."
    assert "articulate deterministic fix" in payload["edits"]
    art = payload["articulate"]
    assert art["route"] == "python" and art["version"] == "9.9.9"
    assert art["gate_before"] == "blocked" and art["gate_after"] == "ok"
    assert art["receipt"]["schema"] == "articulate/editor-receipt/v1"
    assert art["remaining_rule_ids"] == ["r/one"]
    assert "text" not in art
    assert calls == [("deterministic_edit", "flavored"), ("edit_plan", "fix", "flavored"),
                     ("edit_submit", "plan-1")]


def test_meaning_guard_refusal_keeps_the_original(monkeypatch, auto_engine):
    _fake_articulate(monkeypatch, refuse=True)
    payload = clarify_text(DASHED)
    assert payload["engine"] == "articulate"
    assert payload["output"] == DASHED
    assert payload["edits"] == ["kept wording: Articulate's meaning guard refused the rewrite"]
    assert payload["articulate"]["refused"][0]["reasons"] == ["number protected spans changed"]


def test_auto_falls_back_when_articulate_is_absent(monkeypatch, auto_engine, no_articulate_package):
    def missing(name, *a, **kw):
        raise safe_spawn.SpawnRefused("NOT_FOUND", "articulate was not found on PATH")

    monkeypatch.setattr(safe_spawn, "run", missing)
    payload = clarify_text(STIFF)
    assert payload["engine"] == "forum-builtin"
    assert payload["output"] == CLEAN
    assert payload["articulate_unavailable"] == "articulate CLI not usable (NOT_FOUND)"


def test_requested_articulate_engine_fails_loudly_when_absent(monkeypatch, no_articulate_package):
    def missing(name, *a, **kw):
        raise safe_spawn.SpawnRefused("NOT_FOUND", "articulate was not found on PATH")

    monkeypatch.setattr(safe_spawn, "run", missing)
    with pytest.raises(ValueError, match="articulate engine requested but unavailable"):
        clarify_text(STIFF, engine="articulate")


def test_broken_articulate_release_falls_back(monkeypatch, auto_engine):
    _fake_articulate(monkeypatch)

    def broken(*a, **kw):
        raise TypeError("signature changed")

    monkeypatch.setattr(sys.modules["articulate.host_edit"], "deterministic_edit", broken)
    payload = clarify_text(STIFF)
    assert payload["engine"] == "forum-builtin"
    assert payload["articulate_unavailable"] == "articulate python route failed (TypeError)"


class FakeCli:
    """Answers articulate plan/fix/submit the way the real CLI prints them."""

    def __init__(self, exit_code=0):
        self.calls = []
        self.exit_code = exit_code

    def __call__(self, name, args, **kw):
        files = kw["files"]
        argv = args({n: "PRIVATE/" + n for n in files})
        self.calls.append((name, argv, kw))
        if argv[0] == "fix":
            out = {"ok": True, "text": files["candidate.txt"].replace(" — ", ", ")}
        elif argv[0] == "plan":
            out = {"ok": True, "plan_id": "plan-cli"}
        else:
            out = {"ok": True, "text": files["rewrite.txt"], "gate_before": "blocked",
                   "gate_after": "ok", "refused": [], "remaining_findings": [],
                   "receipt": {"schema": "articulate/editor-receipt/v1",
                               "settings": {"ruleset": "sha256:abc"}}}
        return types.SimpleNamespace(returncode=self.exit_code, stdout=json.dumps(out), stderr="")


def test_cli_route_runs_through_safe_spawn_with_no_backend(monkeypatch, auto_engine,
                                                           no_articulate_package):
    cli = FakeCli()
    monkeypatch.setattr(safe_spawn, "run", cli)
    payload = clarify_text(DASHED)
    assert payload["engine"] == "articulate"
    assert payload["output"] == "Before release 2.1, the final one, use the report."
    assert payload["articulate"]["route"] == "cli"
    assert payload["articulate"]["version"] == "cli (ruleset sha256:abc)"
    commands = [argv for _, argv, _ in cli.calls]
    assert [c[0] for c in commands] == ["fix", "plan", "submit"]
    assert commands[0] == ["fix", "PRIVATE/candidate.txt", "--profile", "flavored",
                           "--backend", "none", "--json"]
    assert commands[2] == ["submit", "PRIVATE/original.txt", "PRIVATE/rewrite.txt",
                           "--plan", "plan-cli"]
    for name, _, kw in cli.calls:
        assert name == "articulate"
        assert kw["override_var"] == "FORUM_ARTICULATE_CLI"
        assert kw["set_env"] == {"ARTICULATE_LOCAL_ONLY": "1"}
        assert kw["timeout"] == clarify_articulate.CLI_TIMEOUT_S
        assert "allow_env" not in kw  # the child gets only safe_spawn's base environment


def test_cli_route_failure_falls_back(monkeypatch, auto_engine, no_articulate_package):
    monkeypatch.setattr(safe_spawn, "run", FakeCli(exit_code=2))
    payload = clarify_text(STIFF)
    assert payload["engine"] == "forum-builtin"
    assert payload["articulate_unavailable"] == "articulate fix exited 2"


def test_builtin_engine_opens_no_connection(no_network):
    assert clarify_text(STIFF, engine="forum-builtin")["output"] == CLEAN


def test_real_articulate_package_hands_off_without_network(monkeypatch, no_network):
    pytest.importorskip("articulate.host_edit")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    payload = clarify_text(DASHED, engine="articulate")
    assert payload["articulate"]["route"] == "python"
    assert payload["output"] == "Before release 2.1, the final one, use the report."
    receipt = payload["articulate"]["receipt"]
    assert receipt["schema"] == "articulate/editor-receipt/v1"
    assert receipt["model"] is None


@pytest.mark.skipif(shutil.which("articulate") is None, reason="articulate CLI not on PATH")
def test_real_articulate_cli_hands_off(no_articulate_package):
    payload = clarify_text(DASHED, engine="articulate")
    assert payload["articulate"]["route"] == "cli"
    assert payload["output"] == "Before release 2.1, the final one, use the report."
    assert payload["articulate"]["receipt"]["model"] is None
