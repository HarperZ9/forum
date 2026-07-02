import json

from forum.cli import main
from forum.humanize import HUMANIZE_SCHEMA, humanize_text


def test_humanize_text_removes_model_preamble_and_simplifies_phrasing():
    payload = humanize_text(
        "As an AI language model, it is important to note that in order to utilize this methodology, "
        "the system should provide assistance prior to deployment"
    )
    assert payload["schema"] == HUMANIZE_SCHEMA
    assert payload["output"] == "To use this method, the system should help before deployment."
    assert "removed model preamble" in payload["edits"]
    assert "simplified phrasing" in payload["edits"]
    assert payload["not_verified"] == ["facts were not independently checked"]


def test_humanize_cli_outputs_json(capsys):
    rc = main(["humanize", "Prior to launch, utilize the report in order to assist users."])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["output"] == "Before launch, use the report to help users."
    assert payload["audience"] == "operator"


def test_humanize_text_includes_delivery_profile_check():
    payload = humanize_text(
        "Prior to launch, utilize the module test output.",
        profile="engineer",
    )
    assert payload["profile"] == "engineer"
    assert payload["profile_check"]["schema"] == "forum.delivery-profile/v1"
    assert payload["profile_check"]["profile"] == "engineer"
    assert payload["profile_check"]["flagged"] is False


def test_humanize_cli_accepts_profile(capsys):
    rc = main([
        "humanize",
        "Prior to launch, utilize the module test output.",
        "--profile",
        "engineer",
    ])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["profile"] == "engineer"
    assert payload["profile_check"]["profile"] == "engineer"


def test_humanize_cli_reports_unknown_profile(capsys):
    rc = main(["humanize", "Use the report.", "--profile", "poet"])
    assert rc == 2
    assert "unknown delivery profile" in capsys.readouterr().err
