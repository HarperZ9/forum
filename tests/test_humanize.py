import json

from forum.humanize import HUMANIZE_SCHEMA, humanize_text
from forum.cli import main


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
