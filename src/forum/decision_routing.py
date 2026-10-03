"""Decision routing: a typed choice over the roster with an ABSTAIN outcome.

Each lane is a short document: its keywords (counted twice), its domain
description and the parts of its name. A request is scored against every lane
with BM25, the scores become probabilities with a softmax, and the router
decides the top lane only when its probability reaches ``threshold``. Under
the threshold, or when no lane matches at all, it abstains: ``decided`` is
None and ``needs_escalation`` is True, so the request goes to a person or a
larger model in place of a guessed lane. Deterministic: ties break by name.
"""
from __future__ import annotations

import math
import re

from forum.roster import Roster
from forum.routing import Candidate, RouteResult

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be by can do for from how i in into is it its me my of on "
    "or our please so that the this to up us we what when which why will with you "
    "your".split()
)


def _stem(word: str) -> str:
    for suffix in ("ing", "ies", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def terms(text: str) -> list[str]:
    """Lowercase word tokens, stop words dropped, light suffix stemming."""
    return [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOP]


def lane_document(spec) -> list[str]:
    words = list(spec.keywords) * 2 + [spec.domain, spec.name.replace("-", " ")]
    return terms(" ".join(words))


class _BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.2, b: float = 0.75) -> None:
        self.docs, self.k1, self.b = docs, k1, b
        self.avgdl = sum(len(d) for d in docs) / len(docs) if docs else 0.0
        self.df: dict[str, int] = {}
        for d in docs:
            for t in set(d):
                self.df[t] = self.df.get(t, 0) + 1

    def score(self, query: list[str], i: int) -> float:
        doc, n = self.docs[i], len(self.docs)
        total = 0.0
        for t in set(query):
            f = doc.count(t)
            if not f:
                continue
            idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
            norm = f + self.k1 * (1 - self.b + self.b * len(doc) / (self.avgdl or 1))
            total += idf * f * (self.k1 + 1) / norm
        return total


def probabilities(scores: list[float], temperature: float) -> list[float]:
    """Softmax over lane scores. All-zero scores give a uniform distribution."""
    if not scores:
        return []
    top = max(scores)
    exps = [math.exp((s - top) / temperature) for s in scores]
    z = sum(exps)
    return [e / z for e in exps]


class DecisionRouter:
    """A ``RoutingProvider`` whose candidate scores are lane probabilities.

    The default threshold, 0.0, is the value the dev-half calibration chose on
    the labelled set (docs/DECISION-ROUTING.md): it abstains only when no lane
    matches. Raise it to abstain on weak matches as well.
    """

    def __init__(self, threshold: float = 0.0, temperature: float = 1.0) -> None:
        if not 0.0 <= threshold <= 1.0 or temperature <= 0:
            raise ValueError("threshold must be in [0, 1] and temperature > 0")
        self.threshold = threshold
        self.temperature = temperature

    def lane_probabilities(self, task: str, roster: Roster) -> list[tuple[str, float, float]]:
        """(lane, raw score, probability) for every lane, best first."""
        bm = _BM25([lane_document(s) for s in roster.agents])
        query = terms(task)
        raw = [bm.score(query, i) for i in range(len(roster.agents))]
        probs = probabilities(raw, self.temperature)
        rows = [(s.name, r, p) for s, r, p in zip(roster.agents, raw, probs)]
        rows.sort(key=lambda row: (-row[2], row[0]))
        return rows

    def score(self, task: str, roster: Roster) -> RouteResult:
        rows = self.lane_probabilities(task, roster)
        candidates = tuple(Candidate(name, round(p, 6)) for name, _, p in rows)
        if not rows:
            return RouteResult(candidates, None, 0.0, True)
        name, raw, p = rows[0]
        if raw <= 0 or p < self.threshold:
            return RouteResult(candidates, None, round(p, 6), True)
        return RouteResult(candidates, name, round(p, 6), False)


def calibrate_threshold(router: DecisionRouter, items: list[dict], roster: Roster,
                        abstain_share: float = 0.10) -> float:
    """Lowest threshold whose abstain rate on ``items`` is at least ``abstain_share``.

    Items with no matching lane abstain at any threshold. Use dev items only;
    the threshold is then fixed for the held-out half.
    """
    tops = []
    for item in items:
        rows = router.lane_probabilities(item["text"], roster)
        tops.append(rows[0][2] if rows and rows[0][1] > 0 else -1.0)
    need = math.ceil(abstain_share * len(tops))
    forced = sum(1 for t in tops if t < 0)
    if forced >= need:
        return 0.0
    ranked = sorted(t for t in tops if t >= 0)
    return round(ranked[need - forced - 1] + 1e-9, 9)
