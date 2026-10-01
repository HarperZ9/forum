"""Delivery: a deterministic floor on how an answer reads, plus a reviser seam.

The shortcoming this addresses: model output tends to be word-dense, and the reader
wants the shortest path to the answer. `assess(text)` measures that objectively, the
way `forum.intent` measures coverage: sentence length and filler ratio are computable
and reproducible. It is a floor on concision, not a judgment of cohesion or elegance,
which is the model reviser's rung above it.

The reviser is the peer of the verifier seam: when the floor flags a verbose answer and
a Reviser is configured, Forum pulls a tightened version, then accepts it only if it is
strictly shorter and still covers the request's terms (forum.intent.coverage) before it
replaces the answer. That guard is lexical, not semantic: an accepted revision keeps
every request term the original carried, but coverage cannot see content outside the
request, so it is a floor on dropped terms, not a proof of preserved meaning. A revision
that fails either check is recorded and discarded. The default NullReviser abstains, so
Forum stands alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

_WORD = re.compile(r"[^\W_]+")
_SENTENCE = re.compile(r"[.!?]+")

# Hedges and intensifiers that add length without weight. Frozen for reproducibility.
_FILLER = frozenset({
    "just", "really", "very", "quite", "basically", "actually", "literally",
    "simply", "essentially", "definitely", "certainly", "probably", "perhaps",
    "maybe", "somewhat", "rather", "fairly", "arguably", "clearly", "obviously",
    "honestly", "truly", "indeed", "generally",
})

DEFAULT_MAX_SENTENCE_WORDS = 30.0  # mean words per sentence above this reads as dense
DEFAULT_MAX_FILLER_RATIO = 0.06    # filler words above this share reads as padded


@dataclass(frozen=True, slots=True)
class Delivery:
    words: int
    sentences: int
    mean_sentence_words: float
    filler_ratio: float
    flagged: bool


def assess(
    text: str,
    *,
    max_sentence_words: float = DEFAULT_MAX_SENTENCE_WORDS,
    max_filler_ratio: float = DEFAULT_MAX_FILLER_RATIO,
) -> Delivery:
    """Measure a text's concision: word and sentence counts, mean sentence length, and
    filler ratio, with a flag when it reads as dense or padded. Pure and deterministic.

    A reproducible lexical floor, not a semantic verdict: a flag means the writing is
    long-winded or hedgy enough to be worth tightening, not that it is wrong. Empty or
    content-free text is never flagged.
    """
    words = _WORD.findall(text.lower())
    n_words = len(words)
    sentences = [s for s in _SENTENCE.split(text) if s.strip()]
    n_sentences = len(sentences)
    mean = n_words / n_sentences if n_sentences else float(n_words)
    fillers = sum(1 for w in words if w in _FILLER)
    filler_ratio = fillers / n_words if n_words else 0.0
    flagged = n_words > 0 and (mean > max_sentence_words or filler_ratio > max_filler_ratio)
    return Delivery(n_words, n_sentences, round(mean, 2), round(filler_ratio, 4), flagged)


class Reviser(Protocol):
    """Tightens an answer's delivery, after Forum flags it as dense.

    The peer of the VerifierProvider seam: a brain (the index flagship) or any model
    can implement it. Forum pulls a tighter version, then verifies it before use, so a
    Reviser is trusted no more than a Verifier. Return None to abstain. Forum never
    imports the provider, only this shape. Like the verifier seam, revise() runs
    synchronously inside the run, so a slow reviser blocks the calling run, and under
    the daemon the event loop; keep it quick.
    """

    def revise(self, request: str, answer: str) -> str | None: ...


class NullReviser:
    """The zero-dependency default: no revision. Forum stands alone with the floor only."""

    def revise(self, request: str, answer: str) -> str | None:
        return None
