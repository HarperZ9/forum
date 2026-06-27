from __future__ import annotations

import re

HUMANIZE_SCHEMA = "forum.prose-humanization/v1"

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


def humanize_text(text: str, audience: str = "operator") -> dict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")

    original = text.strip()
    output = original
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
    output = _capitalize_first(output)
    if output and output[-1] not in ".!?":
        output += "."

    return {
        "schema": HUMANIZE_SCHEMA,
        "audience": audience or "operator",
        "input_chars": len(text),
        "output_chars": len(output),
        "output": output,
        "edits": edits or ["kept wording"],
        "not_verified": ["facts were not independently checked"],
    }


def _capitalize_first(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text
