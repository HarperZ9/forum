from __future__ import annotations

from dataclasses import dataclass

from forum.roster import AgentSpec


@dataclass(frozen=True, slots=True)
class Policy:
    allowed_categories: frozenset[str]
    max_parallel: int = 6

    def permits(self, spec: AgentSpec) -> bool:
        return spec.category in self.allowed_categories

    def cap_wave(self, wave: list[str]) -> list[list[str]]:
        n = self.max_parallel
        return [wave[i : i + n] for i in range(0, len(wave), n)]
