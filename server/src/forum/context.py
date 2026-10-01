from __future__ import annotations

from typing import Protocol


class ContextProvider(Protocol):
    """Supplies organized context for a request, before Forum plans or routes.

    This is the seam to the "brain": a peer like the index flagship can implement
    it (rendering its code-and-knowledge map to text), and Forum will witness the
    exact context that shaped a plan. Keep it pure and offline; return "" when
    there is nothing relevant. Forum never imports the provider, only this shape.
    """

    def context(self, request: str) -> str: ...


class NullContextProvider:
    """The zero-dependency default: no external context. Forum stands alone."""

    def context(self, request: str) -> str:
        return ""
