"""Clarify model or agent prose without adding facts.

Two engines produce the output. When Articulate (PyPI ``articulate-writing``) is
importable or its CLI is on PATH, Forum's fixed rules propose a rewrite, Articulate's
deterministic fix runs on it, and Articulate's meaning guard checks the whole change
against the original and issues its editor receipt (``engine="articulate"``).
Otherwise only the fixed rules run (``engine="forum-builtin"``). Neither engine
calls a model or opens a network connection, and neither adds facts.
"""
from __future__ import annotations

import os
import re

from forum.delivery_profile import assess_profile, profile_payload

CLARIFY_SCHEMA = "forum.prose-clarification/v1"
ENGINE_ARTICULATE = "articulate"
ENGINE_BUILTIN = "forum-builtin"
ENGINE_CHOICES = ("auto", ENGINE_ARTICULATE, ENGINE_BUILTIN)
ENGINE_ENV = "FORUM_CLARIFY_ENGINE"

_REPLACEMENTS = (
    (r"\bit is important to note that\s+", ""),
    (r"\bin order to\b", "to"),
    (r"\butilize\b", "use"),
    (r"\butilizing\b", "using"),
    (r"\bmethodology\b", "method"),
    (r"\bprovide assistance\b", "help"),
    (r"\bassist\b", "help"),
    (r"\bprior to\b", "before"),
)

_PREAMBLES = (
    "as an ai language model,",
    "as a language model,",
    "as an ai,",
)


def builtin_rewrite(text: str) -> tuple[str, list[str]]:
    """Apply Forum's fixed rules. Returns (output, edits)."""
    output = text.strip()
    edits: list[str] = []

    lowered = output.lower()
    for preamble in _PREAMBLES:
        if lowered.startswith(preamble):
            output = output[len(preamble):].lstrip()
            edits.append("removed model preamble")
            break

    simplified = output
    for pattern, replacement in _REPLACEMENTS:
        simplified = re.sub(pattern, replacement, simplified, flags=re.IGNORECASE)
    if simplified != output:
        edits.append("simplified phrasing")
    output = simplified

    output = re.sub(r"\s+", " ", output).strip()
    output = output[:1].upper() + output[1:] if output else output
    if output and output[-1] not in ".!?":
        output += "."
    return output, edits


def resolve_engine(engine: str | None) -> str:
    """The requested engine: the argument, else FORUM_CLARIFY_ENGINE, else auto."""
    choice = (engine or os.environ.get(ENGINE_ENV) or "auto").strip().lower()
    if choice not in ENGINE_CHOICES:
        raise ValueError(f"unknown clarify engine {choice!r}; choose one of {', '.join(ENGINE_CHOICES)}")
    return choice


def clarify_text(text: str, audience: str = "operator", profile: str | None = None,
                 engine: str | None = None) -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    requested = resolve_engine(engine)
    original = text.strip()
    candidate, edits = builtin_rewrite(original)

    handoff: dict | None = None
    fallback_reason: str | None = None
    if requested != ENGINE_BUILTIN:
        from forum.clarify_articulate import ArticulateUnavailable, hand_off

        try:
            handoff = hand_off(original, candidate)
        except ArticulateUnavailable as exc:
            if requested == ENGINE_ARTICULATE:
                raise ValueError(f"articulate engine requested but unavailable: {exc}") from exc
            fallback_reason = str(exc)

    if handoff is not None:
        output = handoff.pop("text")
        if output == original and candidate != original:
            edits = ["kept wording: Articulate's meaning guard refused the rewrite"]
        elif output != candidate:
            edits = [*edits, "articulate deterministic fix"]
    else:
        output = candidate

    assessment = assess_profile(output, profile)
    payload = {
        "schema": CLARIFY_SCHEMA,
        "engine": ENGINE_ARTICULATE if handoff is not None else ENGINE_BUILTIN,
        "audience": audience or "operator",
        "profile": assessment.profile,
        "profile_check": profile_payload(assessment),
        "input_chars": len(text),
        "output_chars": len(output),
        "output": output,
        "edits": edits or ["kept wording"],
        "not_verified": ["facts were not independently checked"],
    }
    if handoff is not None:
        payload["articulate"] = handoff
    elif fallback_reason is not None:
        payload["articulate_unavailable"] = fallback_reason
    return payload
