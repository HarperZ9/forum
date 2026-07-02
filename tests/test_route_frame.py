from forum.roster import load_default
from forum.route_frame import ROUTE_FRAME_SCHEMA, derive_route_frame, frame_payload
from forum.routing import LexicalRouter


def _frame(text: str):
    roster = load_default()
    route = LexicalRouter().score(text, roster)
    return derive_route_frame(text, route, roster)


def test_model_foundry_eval_work_gets_architect_frame():
    frame = _frame("build eval gated model promotion for a self improving daemon")
    assert frame.schema == ROUTE_FRAME_SCHEMA
    assert frame.agent == "model-foundry"
    assert frame.domain == "model-foundry"
    assert frame.intent == "validate"
    assert frame.posture == "architect"
    assert frame.delivery_profile == "engineer"
    assert frame.model_tier == "frontier"
    assert frame.executor == "cli"
    assert frame.proof_lane == "validate"
    assert frame.domain_lane == "model-foundry"
    assert "eval" in frame.signals
    assert "gating evidence" in frame.human_contract


def test_evidence_work_gets_investigator_frame():
    frame = _frame("capture browser evidence from a source page with provenance")
    assert frame.domain == "evidence"
    assert frame.intent == "investigate"
    assert frame.posture == "investigator"
    assert frame.delivery_profile == "researcher"
    assert frame.proof_lane == "observe"
    assert frame.domain_lane == "source-federation"


def test_implementation_work_gets_execute_frame():
    frame = _frame("build the api database server endpoint")
    assert frame.agent == "backend"
    assert frame.domain == "implementation"
    assert frame.intent == "execute"
    assert frame.posture == "architect"
    assert frame.delivery_profile == "engineer"
    assert frame.model_tier == "capable"
    assert frame.executor == "cli"
    assert frame.proof_lane == "execute"


def test_weak_request_gets_general_operator_frame():
    frame = _frame("do the thing")
    assert frame.agent is None
    assert frame.domain == "general"
    assert frame.intent == "coordinate"
    assert frame.posture == "operator"
    assert frame.delivery_profile == "operator"
    assert frame.model_tier is None
    assert frame.executor is None
    assert frame.proof_lane is None
    assert frame.domain_lane is None


def test_frame_payload_is_json_ready():
    payload = frame_payload(_frame("teach explain tutor learn lesson"))
    assert payload["schema"] == ROUTE_FRAME_SCHEMA
    assert isinstance(payload["signals"], list)
    assert payload["model_tier"] == "cheap"
    assert payload["executor"] == "cli"
