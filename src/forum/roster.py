from __future__ import annotations

import tomllib
from dataclasses import dataclass

VALID_TIERS = {"cheap", "capable", "frontier"}
_REQUIRED = ("name", "category", "domain", "keywords", "model_tier", "executor")


@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str
    category: str
    domain: str
    keywords: tuple[str, ...]
    model_tier: str
    executor: str
    max_turns: int = 10


@dataclass(frozen=True, slots=True)
class Roster:
    agents: tuple[AgentSpec, ...]

    def by_name(self, name: str) -> AgentSpec | None:
        for a in self.agents:
            if a.name == name:
                return a
        return None


def _spec_from_row(row: dict) -> AgentSpec:
    for field in _REQUIRED:
        if field not in row:
            raise ValueError(f"agent row missing required field: {field!r}")
    if not isinstance(row["keywords"], list):
        raise ValueError(f"agent {row['name']!r}: keywords must be a list")
    keywords = tuple(row["keywords"])
    if not keywords:
        raise ValueError(f"agent {row['name']!r}: keywords must be non-empty")
    if row["model_tier"] not in VALID_TIERS:
        raise ValueError(
            f"agent {row['name']!r}: model_tier must be one of {sorted(VALID_TIERS)}"
        )
    return AgentSpec(
        name=row["name"],
        category=row["category"],
        domain=row["domain"],
        keywords=keywords,
        model_tier=row["model_tier"],
        executor=row["executor"],
        max_turns=int(row.get("max_turns", 10)),
    )


def _roster_from_data(data: dict) -> Roster:
    rows = data.get("agent", [])
    return Roster(tuple(_spec_from_row(r) for r in rows))


def loads(text: str) -> Roster:
    return _roster_from_data(tomllib.loads(text))


def load(path: str) -> Roster:
    with open(path, "rb") as f:
        return _roster_from_data(tomllib.load(f))


def load_default() -> Roster:
    """Load the built-in default roster shipped inside the package.

    Returns the domain-neutral capability lanes so a fresh install has a real
    roster out of the box. Works from a source checkout and from an installed
    wheel, because the manifest ships as package data.
    """
    from importlib.resources import files

    text = (files("forum") / "manifests" / "default-roster.toml").read_text(
        encoding="utf-8"
    )
    return loads(text)
