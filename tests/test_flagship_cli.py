import json

from forum.cli import main


def test_status_json_is_action_envelope(capsys):
    assert main(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "project-telos.flagship-action/v1"
    assert payload["tool"] == "forum"
    assert payload["native"]["role"] == "orchestration-routing"
    assert "forum.ledger.summary" in payload["native"]["mcp_tools"]
    contracts = payload["native"]["telos_contracts"]
    assert "MCP stdio" in contracts["host_surfaces"]
    assert "project-telos.action-receipt/v1" in contracts["schemas"]
    assert "education" in contracts["workflow_domains"]
    assert "humanize outputs" in contracts["second_brain_role"]


def test_doctor_human_prints_next_action(capsys):
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("status=MATCH tool=forum command=doctor")
    assert "next: index context" in out


def test_project_telos_route_lane(capsys):
    request = "improve Project Telos flagship gather crucible index forum provenance workflow"
    assert main(["route", request]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decided"] == "project-telos"
    assert payload["needs_escalation"] is False


def test_model_foundry_route_lane(capsys):
    request = (
        "Build a model foundry self improving daemon with context envelopes, "
        "eval promotion, and receipt chained workflow."
    )
    assert main(["route", request]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decided"] == "model-foundry"
    assert payload["needs_escalation"] is False
