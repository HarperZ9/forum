import asyncio
import json

from forum.engine import Orchestrator
from forum.executor import EchoExecutor, Result
from forum.http_surface import HttpSurface
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.roster import load_default

ALL_CATEGORIES = frozenset({"engineering", "graphics", "support", "research"})


class ScriptedExecutor:
    """Returns valid control-loop JSON, dispatching by role (see run_request.py)."""

    async def run(self, assignment):
        agent = assignment.agent
        if agent == "coordinator":
            out = (
                '{"tasks": ['
                '{"id": "T1", "agent": "backend", "instruction": "design the api", "depends_on": []}'
                "]}"
            )
        elif agent == "validator":
            out = '{"ok": true, "score": 0.9, "reason": "ok"}'
        elif agent == "synthesizer":
            out = "Done: the api is designed."
        else:
            out = "handled: " + assignment.instruction
        return Result(assignment.task_id, assignment.agent, out)


def _surface(executor=None):
    ticks = iter(float(t) for t in range(1, 100_000))
    ledger = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    orch = Orchestrator(
        load_default(), ledger, executor or ScriptedExecutor(),
        Policy(allowed_categories=ALL_CATEGORIES, max_parallel=4),
    )
    return HttpSurface(orch), orch


def _do(surface, method, path, body=b""):
    return asyncio.run(surface.dispatch(method, path, body))


def _json(resp):
    return json.loads(resp.body)


def test_health_returns_ok():
    surface, _ = _surface()
    resp = _do(surface, "GET", "/health")
    assert resp.status == 200
    assert _json(resp) == {"ok": True}


def test_status_on_fresh_ledger():
    surface, _ = _surface()
    resp = _do(surface, "GET", "/status")
    body = _json(resp)
    assert resp.status == 200
    assert body["entries"] == 0
    assert body["checkpoint"] == "0" * 64


def test_route_decides_a_lane():
    surface, _ = _surface()
    resp = _do(surface, "POST", "/route", b'{"text": "build the api database server endpoint"}')
    body = _json(resp)
    assert resp.status == 200
    assert body["decided"] == "backend"
    assert body["candidates"][0]["agent"] == "backend"
    assert body["frame"]["model_tier"] == "capable"
    assert body["frame"]["executor"] == "cli"


def test_route_includes_human_frame():
    surface, _ = _surface()
    resp = _do(
        surface,
        "POST",
        "/route",
        b'{"text": "capture browser evidence from a source page with provenance"}',
    )
    body = _json(resp)
    assert resp.status == 200
    assert body["frame"]["schema"] == "forum.route-frame/v1"
    assert body["frame"]["domain"] == "evidence"
    assert body["frame"]["posture"] == "investigator"
    assert body["frame"]["delivery_profile"] == "researcher"


def test_route_requires_text_field():
    surface, _ = _surface()
    assert _do(surface, "POST", "/route", b'{}').status == 400


def test_plan_returns_tasks():
    surface, _ = _surface()
    resp = _do(surface, "POST", "/plan", b'{"request": "design an api"}')
    body = _json(resp)
    assert resp.status == 200
    assert body["tasks"][0]["id"] == "T1"
    assert body["tasks"][0]["agent"] == "backend"


def test_submit_answers_and_witnesses():
    surface, orch = _surface()
    resp = _do(surface, "POST", "/submit", b'{"request": "build api database server endpoint"}')
    body = _json(resp)
    assert resp.status == 200
    assert body["answer"] == "Done: the api is designed."
    assert body["checkpoint"] == orch.ledger.checkpoint()
    receipt = body["receipt"]
    assert receipt["schema"] == "project-telos.action-receipt/v1"
    assert receipt["tool"] == "forum"
    assert receipt["action"] == "submit"
    assert receipt["action_intent_id"].startswith("sha256:")
    assert receipt["ledger"]["checkpoint"] == orch.ledger.checkpoint()
    assert receipt["ledger"]["verified"] is True
    assert receipt["verification"]["verdict"] == "MATCH"
    assert receipt["request"]["seq"] == 0
    assert receipt["answer"]["seq"] >= receipt["request"]["seq"]
    assert len(receipt["answer"]["payload_hash"]) == 64
    assert receipt["route_frame"]["schema"] == "forum.route-frame/v1"
    assert receipt["route_frame"]["domain"] == "implementation"
    assert receipt["route_frame"]["model_tier"] == "capable"
    assert receipt["route_frame"]["executor"] == "cli"
    assert receipt["delivery_profile"]["selected"] == "engineer"
    assert receipt["delivery_profile"]["source"] == "route_frame"
    # the run was witnessed and is deep-verifiable
    assert orch.ledger.verify(deep=True) is True
    assert len(orch.ledger.replay()) > 0


def test_submit_accepts_context_budget_fields():
    surface, _ = _surface()
    resp = _do(
        surface,
        "POST",
        "/submit",
        b'{"request": "design an api", "context_token_budget": 0}',
    )
    assert resp.status == 200
    body = json.loads(resp.body)
    assert "context_budget" in body["receipt"]


def test_submit_accepts_delivery_profile_field():
    surface, _ = _surface()
    resp = _do(
        surface,
        "POST",
        "/submit",
        b'{"request": "design an api", "delivery_profile": "engineer"}',
    )
    assert resp.status == 200
    body = json.loads(resp.body)
    assert body["receipt"]["delivery_profile"]["requested"] == "engineer"
    assert body["receipt"]["delivery_profile"]["selected"] == "engineer"
    assert body["receipt"]["delivery_profile"]["source"] == "explicit"
    assert body["receipt"]["delivery_profile"]["checks"] == 1


def test_submit_can_checkpoint_each_wave():
    surface, orch = _surface()
    resp = _do(
        surface,
        "POST",
        "/submit",
        b'{"request": "design an api", "checkpoint_each_wave": true}',
    )
    assert resp.status == 200
    assert len(orch.ledger.query(kind="checkpoint")) == 1
    assert orch.ledger.verify(deep=True) is True


def test_submit_rejects_non_boolean_checkpoint_each_wave():
    surface, _ = _surface()
    resp = _do(
        surface,
        "POST",
        "/submit",
        b'{"request": "design an api", "checkpoint_each_wave": "yes"}',
    )
    assert resp.status == 400
    assert "checkpoint_each_wave" in json.loads(resp.body)["error"]


def test_submit_rejects_unknown_delivery_profile():
    surface, _ = _surface()
    resp = _do(
        surface,
        "POST",
        "/submit",
        b'{"request": "design an api", "delivery_profile": "poet"}',
    )
    assert resp.status == 400
    assert "unknown delivery profile" in json.loads(resp.body)["error"]


def test_capsule_returns_context_capsule():
    surface, _ = _surface()
    _do(surface, "POST", "/submit", b'{"request": "design an api"}')
    resp = _do(surface, "GET", "/capsule")
    body = json.loads(resp.body)
    assert resp.status == 200
    assert body["schema"] == "forum.context-capsule/v1"
    assert body["latest_answer"] == "Done: the api is designed."


def test_room_returns_run_room_snapshot():
    surface, _ = _surface()
    _do(surface, "POST", "/submit", b'{"request": "build api database server endpoint"}')
    resp = _do(surface, "GET", "/room")
    body = json.loads(resp.body)
    assert resp.status == 200
    assert body["schema"] == "forum.run-room/v1"
    assert body["request"]["text"] == "build api database server endpoint"
    assert body["route_frame"]["model_tier"] == "capable"
    assert body["route_frame"]["executor"] == "cli"
    assert body["answer"]["text"] == "Done: the api is designed."
    assert body["tasks"][0]["id"] == "T1"


def test_ledger_get_and_replay_after_submit():
    surface, orch = _surface()
    _do(surface, "POST", "/submit", b'{"request": "design an api"}')
    first = _do(surface, "GET", "/ledger/0")
    assert first.status == 200
    assert _json(first)["kind"] == "request"
    replay = _do(surface, "GET", "/replay/0")
    assert [e["seq"] for e in _json(replay)["entries"]] == [0]


def test_ledger_get_missing_is_404():
    surface, _ = _surface()
    assert _do(surface, "GET", "/ledger/999").status == 404


def test_ledger_get_non_integer_is_400():
    surface, _ = _surface()
    assert _do(surface, "GET", "/ledger/abc").status == 400


def test_verify_and_checkpoint():
    surface, orch = _surface()
    _do(surface, "POST", "/submit", b'{"request": "design an api"}')
    v = _json(_do(surface, "GET", "/verify"))
    assert v == {"chain": True, "deep": True}
    c = _json(_do(surface, "GET", "/checkpoint"))
    assert c["checkpoint"] == orch.ledger.checkpoint()


def test_unknown_path_is_404():
    surface, _ = _surface()
    assert _do(surface, "GET", "/nope").status == 404


def test_wrong_method_is_405():
    surface, _ = _surface()
    assert _do(surface, "POST", "/status", b"{}").status == 405


def test_wrong_method_on_ledger_and_replay_prefixes_is_405():
    # The 405 fallback's prefix arm: a known resource, an unsupported method.
    surface, _ = _surface()
    assert _do(surface, "DELETE", "/ledger/0", b"").status == 405
    assert _do(surface, "DELETE", "/replay/0", b"").status == 405


def test_submit_bad_json_is_400():
    surface, _ = _surface()
    assert _do(surface, "POST", "/submit", b"not json").status == 400


def test_submit_missing_body_is_400():
    surface, _ = _surface()
    assert _do(surface, "POST", "/submit").status == 400


def test_submit_with_echo_executor_is_502():
    # EchoExecutor cannot produce the JSON the control loop needs; the daemon
    # surfaces that as a clear 502, not a 500.
    surface, _ = _surface(executor=EchoExecutor())
    resp = _do(surface, "POST", "/submit", b'{"request": "design an api"}')
    assert resp.status == 502


def test_plan_with_echo_executor_is_502():
    surface, _ = _surface(executor=EchoExecutor())
    assert _do(surface, "POST", "/plan", b'{"request": "design an api"}').status == 502


def test_humanize_simplifies_agent_prose():
    surface, _ = _surface()
    resp = asyncio.run(
        surface.dispatch(
            "POST",
            "/humanize",
            b'{"text":"As an AI language model, prior to launch utilize the report in order to assist users."}',
        )
    )
    assert resp.status == 200
    body = json.loads(resp.body)
    assert body["schema"] == "forum.prose-humanization/v1"
    assert body["output"] == "Before launch use the report to help users."
    assert "facts were not independently checked" in body["not_verified"]


def test_humanize_accepts_delivery_profile():
    surface, _ = _surface()
    resp = asyncio.run(
        surface.dispatch(
            "POST",
            "/humanize",
            b'{"text":"Prior to launch, utilize the module test output.","profile":"engineer"}',
        )
    )
    assert resp.status == 200
    body = json.loads(resp.body)
    assert body["profile"] == "engineer"
    assert body["profile_check"]["profile"] == "engineer"


def test_humanize_rejects_unknown_delivery_profile():
    surface, _ = _surface()
    resp = asyncio.run(
        surface.dispatch("POST", "/humanize", b'{"text":"Use the report.","profile":"poet"}')
    )
    assert resp.status == 400
    assert "unknown delivery profile" in json.loads(resp.body)["error"]
