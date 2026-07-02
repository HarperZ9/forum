from forum.communication_contract import (
    COMMUNICATION_CONTRACT_SCHEMA,
    build_communication_contract,
    communication_contract_text,
)


def test_engineer_architect_contract_is_json_ready():
    contract = build_communication_contract(
        domain="implementation",
        intent="execute",
        posture="architect",
        profile="engineer",
    )
    assert contract["schema"] == COMMUNICATION_CONTRACT_SCHEMA
    assert contract["domain"] == "implementation"
    assert contract["intent"] == "execute"
    assert contract["posture"] == "architect"
    assert contract["profile"] == "engineer"
    assert contract["lead"] == "Lead with the concrete change or decision."
    assert "verification" in contract["structure"]
    assert "name files, commands, tests, or ledger facts when available" in contract["evidence"]
    assert "model preambles" in contract["avoid"]
    assert "name the mechanism" in contract["required_moves"]


def test_contract_text_is_prompt_ready():
    contract = build_communication_contract(
        domain="evidence",
        intent="investigate",
        posture="investigator",
        profile="researcher",
    )
    text = communication_contract_text(contract)
    assert "Communication contract:" in text
    assert "Posture: investigator / researcher" in text
    assert "Lead: Lead with what was observed, then what is inferred." in text
    assert "Evidence: separate observation from inference" in text
    assert "Avoid: model preambles" in text
