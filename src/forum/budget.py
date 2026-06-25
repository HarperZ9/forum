from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunBudget:
    """A ceiling on a single run, so a loop cannot quietly run away.

    ``max_model_calls`` caps how many times the executor is invoked across the
    whole run (planning, dispatch, validation, synthesis); it is deterministic
    and is the cost-relevant dimension. ``max_seconds`` is a best-effort wall
    clock cap. A breach of either stops the run gracefully and is witnessed in
    the ledger as a ``budget`` entry; the run stays verifiable.
    """

    max_model_calls: int | None = None
    max_seconds: float | None = None
