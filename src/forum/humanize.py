"""Deprecated alias for forum.clarify, kept for one release.

`humanize_text` returns the clarify result with the old schema id and a
`deprecation` notice. Every humanize name (this module, the `forum humanize`
command, `POST /humanize` and the `forum.prose.humanize` MCP tool) is due for
removal in the release after the one that introduced clarify.
"""
from __future__ import annotations

from forum.clarify import clarify_text

HUMANIZE_SCHEMA = "forum.prose-humanization/v1"
DEPRECATION = {
    "deprecated": True,
    "replacement": "clarify",
    "message": (
        "humanize is renamed to clarify (forum clarify, POST /clarify, forum.prose.clarify); "
        "the humanize names are removed in the release after the one that adds clarify"
    ),
    "removal": "the release after the one that adds clarify",
}


def deprecated(payload: dict) -> dict:
    """The clarify payload as the humanize alias returns it."""
    out = dict(payload)
    out["schema"] = HUMANIZE_SCHEMA
    out["deprecation"] = dict(DEPRECATION)
    return out


def humanize_text(text: str, audience: str = "operator", profile: str | None = None,
                  engine: str | None = None) -> dict:
    return deprecated(clarify_text(text, audience=audience, profile=profile, engine=engine))
