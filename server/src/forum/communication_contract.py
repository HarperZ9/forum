from __future__ import annotations

from forum.delivery_profile import get_profile

COMMUNICATION_CONTRACT_SCHEMA = "forum.communication-contract/v1"

_AVOID = (
    "model preambles",
    "unsupported superlatives",
    "vague optimism",
    "performative hedging",
)

_LEADS = {
    "architect": "Lead with the concrete change or decision.",
    "investigator": "Lead with what was observed, then what is inferred.",
    "reviewer": "Lead with the verdict and the check performed.",
    "teacher": "Lead from the learner's current frame.",
    "operator": "Lead with status, tradeoff, and next action.",
}

_STRUCTURE_BY_PROFILE = {
    "engineer": ("change", "interface", "verification", "risk", "next step"),
    "researcher": ("observation", "source", "inference", "unknowns", "next check"),
    "executive": ("decision", "tradeoff", "owner", "risk", "next action"),
    "operator": ("status", "route", "uncertainty", "next step"),
}

_EVIDENCE_BY_PROFILE = {
    "engineer": ("name files, commands, tests, or ledger facts when available",),
    "researcher": ("separate observation from inference", "name sources or unknowns"),
    "executive": ("name the basis for the recommendation",),
    "operator": ("state what is verified and what remains uncertain",),
}

_MOVES_BY_POSTURE = {
    "architect": ("name the mechanism", "separate verified output from next work"),
    "investigator": ("preserve provenance", "separate observations from inference"),
    "reviewer": ("state pass or fail", "name remaining risk"),
    "teacher": ("give one clear example", "make the check for understanding explicit"),
    "operator": ("name the owner", "state the next coordinated action"),
}


def build_communication_contract(
    *,
    domain: str,
    intent: str,
    posture: str,
    profile: str | None,
    human_contract: str = "",
    proof_lane: str | None = None,
    domain_lane: str | None = None,
) -> dict:
    normalized_profile = get_profile(profile).name
    normalized_posture = posture or "operator"
    return {
        "schema": COMMUNICATION_CONTRACT_SCHEMA,
        "domain": domain or "general",
        "intent": intent or "coordinate",
        "posture": normalized_posture,
        "profile": normalized_profile,
        "proof_lane": proof_lane,
        "domain_lane": domain_lane,
        "lead": _LEADS.get(normalized_posture, _LEADS["operator"]),
        "structure": list(_STRUCTURE_BY_PROFILE.get(normalized_profile, _STRUCTURE_BY_PROFILE["operator"])),
        "evidence": list(_EVIDENCE_BY_PROFILE.get(normalized_profile, _EVIDENCE_BY_PROFILE["operator"])),
        "avoid": list(_AVOID),
        "required_moves": list(_MOVES_BY_POSTURE.get(normalized_posture, _MOVES_BY_POSTURE["operator"])),
        "human_contract": human_contract,
    }


def communication_contract_text(contract: dict) -> str:
    return "\n".join(
        [
            "Communication contract:",
            f"Posture: {contract.get('posture', 'operator')} / {contract.get('profile', 'operator')}",
            f"Domain: {contract.get('domain', 'general')} / {contract.get('intent', 'coordinate')}",
            f"Lead: {contract.get('lead', '')}",
            f"Structure: {_join(contract.get('structure') or [])}",
            f"Evidence: {_join(contract.get('evidence') or [], sep='; ')}",
            f"Avoid: {_join(contract.get('avoid') or [])}",
            f"Required moves: {_join(contract.get('required_moves') or [])}",
            f"Route contract: {contract.get('human_contract', '')}",
        ]
    )


def _join(values: list[str], *, sep: str = ", ") -> str:
    return sep.join(str(value) for value in values)
