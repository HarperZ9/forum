"""Intent coverage: how much of a request's vocabulary the final answer reflects.

This is a deterministic, reproducible *lexical* floor, not a semantic judgment. It
answers a narrow, honest question: of the content words in the original request, how
many show up in the answer the run produced? A low score flags a run for a closer
look (the answer may have drifted from what was asked), it does not declare the answer
wrong. A grounded model intent-judge is the next rung above this floor.

Pure standard library, deterministic: the same request and answer always score the
same, so the signal is as re-checkable as everything else Forum witnesses.
"""

from __future__ import annotations

import re

# Unicode-aware word tokens (letters and digits, any script), excluding underscore
# so snake_case splits into words. Deterministic: a pure function of the input text.
_TOKEN = re.compile(r"[^\W_]+")

# Function words only: articles, conjunctions, prepositions, pronouns, auxiliaries.
# Deliberately minimal and frozen so the score is reproducible across versions.
# Content words (including verbs like "build") are kept, because they carry intent.
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "nor", "but", "so", "yet", "for",
    "if", "then", "than", "as", "of", "to", "in", "on", "at", "by",
    "with", "from", "into", "onto", "off", "out", "up", "down", "over", "per", "via",
    "is", "are", "was", "were", "be", "been", "being", "am",
    "it", "its", "this", "that", "these", "those",
    "i", "you", "we", "they", "he", "she", "him", "her", "them", "me", "us",
    "my", "your", "our", "their", "his", "hers", "ours", "yours",
    "do", "does", "did", "can", "could", "should", "would", "will", "shall", "may", "might", "must",
    "have", "has", "had", "not", "no", "yes", "all", "any", "some", "more", "most",
})

_MIN_LEN = 2  # drop single characters (often noise once punctuation is split off)

# Coverage at or above this is not flagged. A floor for "worth a look", not a pass
# mark; tune per deployment via Orchestrator(intent_threshold=...).
DEFAULT_THRESHOLD = 0.5


def salient_terms(text: str) -> set[str]:
    """The content tokens in text: lowercased letter and digit runs (Unicode-aware,
    so non-Latin scripts are kept and underscores split), minus a fixed function-word
    stoplist and single characters. Pure and deterministic."""
    return {t for t in _TOKEN.findall(text.lower()) if len(t) >= _MIN_LEN and t not in _STOPWORDS}


def coverage(request: str, answer: str) -> tuple[float, set[str]]:
    """How much of the request's salient vocabulary the answer reflects.

    Returns ``(fraction in [0, 1], the request terms missing from the answer)``. A
    request with no salient terms is fully covered by definition (``1.0``, empty),
    so a content-free request never reads as drift. This is a reproducible lexical
    floor, not a semantic verdict: a low fraction flags a run for review, it does
    not mean the answer is wrong.
    """
    req_terms = salient_terms(request)
    if not req_terms:
        return 1.0, set()
    missing = req_terms - salient_terms(answer)
    covered = len(req_terms) - len(missing)
    return covered / len(req_terms), missing
