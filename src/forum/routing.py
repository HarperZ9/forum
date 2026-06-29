from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from forum.roster import Roster

_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class Candidate:
    agent: str
    score: float


@dataclass(frozen=True, slots=True)
class RouteResult:
    candidates: tuple[Candidate, ...]
    decided: str | None
    confidence: float
    needs_escalation: bool


class RoutingProvider(Protocol):
    def score(self, task: str, roster: Roster) -> RouteResult: ...


class LexicalRouter:
    def __init__(
        self,
        threshold: float = 0.5,
        margin: float = 0.15,
        decisive_hits: int = 3,
        hit_margin: int = 2,
    ) -> None:
        self._threshold = threshold
        self._margin = margin
        self._decisive_hits = decisive_hits
        self._hit_margin = hit_margin

    def score(self, task: str, roster: Roster) -> RouteResult:
        tokens = set(_TOKEN.findall(task.lower()))
        scored: list[Candidate] = []
        hit_counts: dict[str, int] = {}
        for spec in roster.agents:
            hits = sum(1 for kw in spec.keywords if kw.lower() in tokens)
            norm = hits / len(spec.keywords) if spec.keywords else 0.0
            scored.append(Candidate(spec.name, norm))
            hit_counts[spec.name] = hits
        scored.sort(key=lambda c: (-c.score, c.agent))
        candidates = tuple(scored)

        top = candidates[0].score if candidates else 0.0
        second = candidates[1].score if len(candidates) > 1 else 0.0
        top_hits = hit_counts.get(candidates[0].agent, 0) if candidates else 0
        second_hits = hit_counts.get(candidates[1].agent, 0) if len(candidates) > 1 else 0

        if top >= self._threshold and (top - second) >= self._margin:
            return RouteResult(candidates, candidates[0].agent, top, False)
        if (
            top_hits >= self._decisive_hits
            and (top_hits - second_hits) >= self._hit_margin
        ):
            return RouteResult(candidates, candidates[0].agent, max(top, self._threshold), False)
        return RouteResult(candidates, None, top - second, True)
