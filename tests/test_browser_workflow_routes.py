from forum.roster import load_default
from forum.routing import LexicalRouter


def route(text):
    return LexicalRouter().score(text, load_default())


def test_browser_research_capture_routes_to_project_telos():
    result = route("Use Telos browser evidence to capture a JavaScript-rendered source page with DOM and screenshot refs")
    assert result.decided == "project-telos"
    assert result.needs_escalation is False


def test_browser_work_actuation_routes_to_project_telos():
    result = route("Run an operator-authorized work-actuate browser workflow and record before after evidence")
    assert result.decided == "project-telos"
    assert result.needs_escalation is False


def test_model_council_browser_pipeline_routes_to_project_telos():
    result = route("Use index and forum model council routing over browser evidence for local model pipeline review")
    assert result.decided == "project-telos"
    assert result.needs_escalation is False


def test_learn_credential_boundary_routes_to_teaching_or_telos():
    result = route("Use browser automation for learn credential logistics but halt on human assessment")
    assert result.decided in {"project-telos", "teaching"}
    assert result.needs_escalation is False
