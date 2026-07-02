import pytest

from forum.delivery_profile import (
    DELIVERY_PROFILE_SCHEMA,
    assess_profile,
    get_profile,
    list_profiles,
    profile_payload,
)


def _codes(assessment):
    return {finding.code for finding in assessment.findings}


def test_list_profiles_and_default_profile():
    assert list_profiles() == ("operator", "engineer", "researcher", "executive")
    assert get_profile(None).name == "operator"
    assert get_profile("engineer").name == "engineer"


def test_unknown_profile_names_valid_options():
    with pytest.raises(ValueError) as exc:
        get_profile("poet")
    msg = str(exc.value)
    assert "unknown delivery profile" in msg
    assert "operator" in msg and "engineer" in msg and "researcher" in msg and "executive" in msg


def test_empty_text_is_flagged():
    assessment = assess_profile("", "operator")
    assert assessment.flagged is True
    assert "empty_text" in _codes(assessment)


def test_model_preamble_and_ai_disclaimer_are_flagged():
    assessment = assess_profile("As an AI language model, I cannot inspect the repo.", "operator")
    codes = _codes(assessment)
    assert "model_preamble" in codes
    assert "model_disclaimer" in codes


def test_operator_profile_accepts_direct_concise_action():
    assessment = assess_profile("Ship the API. Run the focused tests. Report the checkpoint.", "operator")
    assert assessment.flagged is False
    assert assessment.findings == ()


def test_operator_profile_flags_indirect_opening_and_missing_action():
    assessment = assess_profile("It seems the system may be ready. The status is acceptable.", "operator")
    codes = _codes(assessment)
    assert "banned_start" in codes
    assert "missing_action_verb" in codes


def test_engineer_profile_flags_vague_unsupported_optimization():
    assessment = assess_profile("Optimize the system and make it better.", "engineer")
    codes = _codes(assessment)
    assert "missing_required_term" in codes
    assert "vague_optimization" in codes


def test_engineer_profile_accepts_concrete_verified_language():
    text = "The module passes the focused test from the ledger. Keep the API unchanged."
    assessment = assess_profile(text, "engineer")
    assert assessment.flagged is False


def test_researcher_profile_requires_evidence_language():
    assessment = assess_profile("This proves the model is better than the baseline.", "researcher")
    codes = _codes(assessment)
    assert "missing_evidence_language" in codes
    assert "overconfident_without_evidence" in codes


def test_researcher_profile_accepts_sourced_language():
    text = "The source reports lower context pressure. Unknown cases remain outside this sample."
    assessment = assess_profile(text, "researcher")
    assert assessment.flagged is False


def test_executive_profile_flags_long_or_indirect_answers():
    text = "Maybe the project is ready. " + " ".join(["detail"] * 130)
    assessment = assess_profile(text, "executive")
    codes = _codes(assessment)
    assert "banned_start" in codes
    assert "too_many_words" in codes


def test_profile_payload_is_json_ready():
    assessment = assess_profile("Ship the API. Run the tests.", "operator")
    payload = profile_payload(assessment)
    assert payload["schema"] == DELIVERY_PROFILE_SCHEMA
    assert payload["profile"] == "operator"
    assert payload["flagged"] is False
    assert payload["findings"] == []
