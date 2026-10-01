from __future__ import annotations

import re
from dataclasses import dataclass

DELIVERY_PROFILE_SCHEMA = "forum.delivery-profile/v1"

_WORD = re.compile(r"[^\W_]+")
_SENTENCE = re.compile(r"[.!?]+")

_FILLER = frozenset({
    "just",
    "really",
    "very",
    "quite",
    "basically",
    "actually",
    "literally",
    "simply",
    "essentially",
    "definitely",
    "certainly",
    "probably",
    "perhaps",
    "maybe",
    "somewhat",
    "rather",
    "fairly",
    "arguably",
    "clearly",
    "obviously",
    "honestly",
    "truly",
    "indeed",
    "generally",
})

_ACTION_VERBS = frozenset({
    "ship",
    "run",
    "fix",
    "build",
    "verify",
    "commit",
    "report",
    "review",
    "deploy",
    "write",
    "read",
    "test",
    "measure",
    "compare",
    "record",
    "keep",
})

_EVIDENCE_TERMS = frozenset({
    "source",
    "citation",
    "observed",
    "measured",
    "reported",
    "unknown",
    "verified",
    "not verified",
    "from the test output",
    "test output",
    "from the ledger",
})

_TECHNICAL_TERMS = frozenset({
    "file",
    "test",
    "api",
    "module",
    "function",
    "command",
    "error",
    "schema",
    "ledger",
    "route",
    "class",
    "method",
    "commit",
    "http",
    "mcp",
    "cli",
})

_BANNED_STARTS = (
    "it seems",
    "maybe",
    "perhaps",
    "i think",
    "as an ai",
    "as a language model",
)

_MODEL_PREAMBLES = (
    "as an ai language model",
    "as a language model",
    "as an ai",
)

_MODEL_DISCLAIMERS = (
    "i cannot",
    "i can't",
    "i do not have access",
    "i don't have access",
)

_OVERCONFIDENT = frozenset({"proves", "certainly", "obviously", "definitely"})


@dataclass(frozen=True, slots=True)
class DeliveryProfile:
    name: str
    max_mean_sentence_words: float
    max_filler_ratio: float
    max_words: int | None = None
    banned_starts: tuple[str, ...] = _BANNED_STARTS
    banned_phrases: tuple[str, ...] = ()
    required_terms: tuple[str, ...] = ()
    requires_action_verb: bool = False
    requires_evidence_language: bool = False
    direct_opening: bool = False


@dataclass(frozen=True, slots=True)
class ProfileFinding:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class ProfileAssessment:
    profile: str
    words: int
    sentences: int
    mean_sentence_words: float
    filler_ratio: float
    flagged: bool
    findings: tuple[ProfileFinding, ...]
    schema: str = DELIVERY_PROFILE_SCHEMA


_PROFILES = {
    "operator": DeliveryProfile(
        name="operator",
        max_mean_sentence_words=24.0,
        max_filler_ratio=0.04,
        requires_action_verb=True,
        direct_opening=True,
    ),
    "engineer": DeliveryProfile(
        name="engineer",
        max_mean_sentence_words=24.0,
        max_filler_ratio=0.04,
        required_terms=tuple(sorted(_TECHNICAL_TERMS)),
        requires_action_verb=True,
        requires_evidence_language=True,
        direct_opening=True,
    ),
    "researcher": DeliveryProfile(
        name="researcher",
        max_mean_sentence_words=24.0,
        max_filler_ratio=0.04,
        requires_evidence_language=True,
        direct_opening=True,
    ),
    "executive": DeliveryProfile(
        name="executive",
        max_mean_sentence_words=24.0,
        max_filler_ratio=0.04,
        max_words=120,
        requires_action_verb=True,
        direct_opening=True,
    ),
}


def list_profiles() -> tuple[str, ...]:
    return tuple(_PROFILES)


def get_profile(name: str | None) -> DeliveryProfile:
    key = "operator" if name is None else str(name).strip().lower()
    try:
        return _PROFILES[key]
    except KeyError as exc:
        valid = ", ".join(list_profiles())
        raise ValueError(
            f"unknown delivery profile {name!r}; valid profiles: {valid}"
        ) from exc


def assess_profile(
    text: str,
    profile: str | DeliveryProfile | None = None,
) -> ProfileAssessment:
    p = profile if isinstance(profile, DeliveryProfile) else get_profile(profile)
    raw = text or ""
    lowered = raw.strip().lower()
    words = _WORD.findall(lowered)
    word_count = len(words)
    sentence_count = len([s for s in _SENTENCE.split(raw) if s.strip()])
    mean = round(word_count / sentence_count, 2) if sentence_count else float(word_count)
    filler_ratio = (
        round(sum(1 for word in words if word in _FILLER) / word_count, 4)
        if word_count
        else 0.0
    )
    findings: list[ProfileFinding] = []

    if not lowered:
        findings.append(ProfileFinding("empty_text", "delivered text is empty"))
    if any(lowered.startswith(prefix) for prefix in _MODEL_PREAMBLES):
        findings.append(ProfileFinding("model_preamble", "text starts with a model preamble"))
    if any(phrase in lowered for phrase in _MODEL_DISCLAIMERS):
        findings.append(
            ProfileFinding("model_disclaimer", "text contains a first-person model disclaimer")
        )
    banned_start = next((start for start in p.banned_starts if lowered.startswith(start)), None)
    if banned_start:
        findings.append(ProfileFinding("banned_start", f"text starts with {banned_start!r}"))
    banned_phrase = next((phrase for phrase in p.banned_phrases if phrase in lowered), None)
    if banned_phrase:
        findings.append(
            ProfileFinding("banned_phrase", f"text contains banned phrase {banned_phrase!r}")
        )
    if word_count and mean > p.max_mean_sentence_words:
        findings.append(
            ProfileFinding(
                "long_sentence",
                f"mean sentence words {mean} exceeds {p.max_mean_sentence_words}",
            )
        )
    if word_count and filler_ratio > p.max_filler_ratio:
        findings.append(
            ProfileFinding(
                "filler_ratio",
                f"filler ratio {filler_ratio} exceeds {p.max_filler_ratio}",
            )
        )
    if p.max_words is not None and word_count > p.max_words:
        findings.append(
            ProfileFinding("too_many_words", f"word count {word_count} exceeds {p.max_words}")
        )
    if (
        p.requires_action_verb
        and sentence_count > 1
        and not any(word in _ACTION_VERBS for word in words)
    ):
        findings.append(
            ProfileFinding("missing_action_verb", "profile requires a concrete action verb")
        )
    if p.required_terms and not any(term in words for term in p.required_terms):
        findings.append(
            ProfileFinding(
                "missing_required_term",
                f"{p.name} profile requires a concrete technical term",
            )
        )
    has_evidence = _has_phrase(lowered, _EVIDENCE_TERMS)
    if p.requires_evidence_language and not has_evidence:
        findings.append(
            ProfileFinding(
                "missing_evidence_language",
                f"{p.name} profile requires evidence language",
            )
        )
    if "optimize" in words and not any(char.isdigit() for char in lowered):
        findings.append(
            ProfileFinding("vague_optimization", "optimization claim needs a measurable target")
        )
    if any(word in _OVERCONFIDENT for word in words) and not has_evidence:
        findings.append(
            ProfileFinding(
                "overconfident_without_evidence",
                "overconfident wording needs evidence language",
            )
        )

    return ProfileAssessment(
        profile=p.name,
        words=word_count,
        sentences=sentence_count,
        mean_sentence_words=mean,
        filler_ratio=filler_ratio,
        flagged=bool(findings),
        findings=tuple(findings),
    )


def profile_payload(assessment: ProfileAssessment) -> dict:
    return {
        "schema": assessment.schema,
        "profile": assessment.profile,
        "words": assessment.words,
        "sentences": assessment.sentences,
        "mean_sentence_words": assessment.mean_sentence_words,
        "filler_ratio": assessment.filler_ratio,
        "flagged": assessment.flagged,
        "findings": [
            {"code": finding.code, "detail": finding.detail}
            for finding in assessment.findings
        ],
    }


def _has_phrase(text: str, phrases: frozenset[str]) -> bool:
    tokens = set(_WORD.findall(text))
    return any((" " in phrase and phrase in text) or phrase in tokens for phrase in phrases)
