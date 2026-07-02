from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA = "forum.context-pressure/v1"
DEFAULT_BYTES_PER_TOKEN = 4

SOURCES = frozenset({"request", "task", "upstream"})


@dataclass(frozen=True, slots=True)
class ContextBudget:
    max_total_tokens: int | None = None
    max_request_tokens: int | None = None
    max_task_tokens: int | None = None
    max_upstream_tokens: int | None = None
    bytes_per_token: int = DEFAULT_BYTES_PER_TOKEN

    def __post_init__(self) -> None:
        for name in (
            "max_total_tokens",
            "max_request_tokens",
            "max_task_tokens",
            "max_upstream_tokens",
        ):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.bytes_per_token <= 0:
            raise ValueError("bytes_per_token must be > 0")

    def limit_for(self, source: str) -> int | None:
        if source == "request":
            return self.max_request_tokens
        if source == "task":
            return self.max_task_tokens
        if source == "upstream":
            return self.max_upstream_tokens
        raise ValueError(f"unknown context source: {source}")

    def configured_limits(self) -> dict[str, int]:
        limits: dict[str, int] = {"bytes_per_token": self.bytes_per_token}
        for key in (
            "max_total_tokens",
            "max_request_tokens",
            "max_task_tokens",
            "max_upstream_tokens",
        ):
            value = getattr(self, key)
            if value is not None:
                limits[key] = value
        return limits


@dataclass(frozen=True, slots=True)
class ContextPressure:
    source: str
    label: str
    original_bytes: int
    admitted_bytes: int
    original_tokens: int
    admitted_tokens: int
    action: str
    reason: str


@dataclass(slots=True)
class ContextBudgetMeter:
    admitted_tokens_total: int = 0
    pressures: list[ContextPressure] = field(default_factory=list)

    def remaining_total(self, budget: ContextBudget) -> int | None:
        if budget.max_total_tokens is None:
            return None
        return max(0, budget.max_total_tokens - self.admitted_tokens_total)

    def record(self, pressure: ContextPressure) -> None:
        self.admitted_tokens_total += pressure.admitted_tokens
        self.pressures.append(pressure)


def approx_tokens(text: str, bytes_per_token: int = DEFAULT_BYTES_PER_TOKEN) -> int:
    if bytes_per_token <= 0:
        raise ValueError("bytes_per_token must be > 0")
    byte_count = len(text.encode("utf-8"))
    if byte_count == 0:
        return 0
    return (byte_count + bytes_per_token - 1) // bytes_per_token


def apply_context_budget(
    source: str,
    label: str,
    text: str,
    budget: ContextBudget,
    meter: ContextBudgetMeter,
) -> tuple[str, ContextPressure]:
    if source not in SOURCES:
        raise ValueError(f"unknown context source: {source}")
    original_bytes = len(text.encode("utf-8"))
    original_tokens = approx_tokens(text, budget.bytes_per_token)
    if original_tokens == 0:
        pressure = ContextPressure(source, label, original_bytes, 0, 0, 0, "retained", "empty")
        meter.record(pressure)
        return "", pressure

    limit, reason = _effective_limit(source, budget, meter)
    if limit is None or original_tokens <= limit:
        pressure = ContextPressure(
            source,
            label,
            original_bytes,
            original_bytes,
            original_tokens,
            original_tokens,
            "retained",
            "under_budget",
        )
        meter.record(pressure)
        return text, pressure
    if limit <= 0:
        pressure = ContextPressure(
            source,
            label,
            original_bytes,
            0,
            original_tokens,
            0,
            "omitted",
            reason,
        )
        meter.record(pressure)
        return "", pressure

    admitted = _slice_utf8(text, limit * budget.bytes_per_token)
    admitted_bytes = len(admitted.encode("utf-8"))
    admitted_tokens = approx_tokens(admitted, budget.bytes_per_token)
    pressure = ContextPressure(
        source,
        label,
        original_bytes,
        admitted_bytes,
        original_tokens,
        admitted_tokens,
        "trimmed",
        reason,
    )
    meter.record(pressure)
    return admitted, pressure


def pressure_payload(
    pressure: ContextPressure,
    budget: ContextBudget,
    meter: ContextBudgetMeter,
) -> dict:
    return {
        "schema": SCHEMA,
        "source": pressure.source,
        "label": pressure.label,
        "action": pressure.action,
        "reason": pressure.reason,
        "original_bytes": pressure.original_bytes,
        "admitted_bytes": pressure.admitted_bytes,
        "original_tokens": pressure.original_tokens,
        "admitted_tokens": pressure.admitted_tokens,
        "remaining_total_tokens": meter.remaining_total(budget),
    }


def observed_context_budget(pressures: list[ContextPressure]) -> dict:
    original = sum(pressure.original_tokens for pressure in pressures)
    admitted = sum(pressure.admitted_tokens for pressure in pressures)
    return {
        "checks": len(pressures),
        "trimmed": sum(1 for pressure in pressures if pressure.action == "trimmed"),
        "omitted": sum(1 for pressure in pressures if pressure.action == "omitted"),
        "tokens_original": original,
        "tokens_admitted": admitted,
        "tokens_saved": original - admitted,
    }


def _effective_limit(
    source: str,
    budget: ContextBudget,
    meter: ContextBudgetMeter,
) -> tuple[int | None, str]:
    source_limit = budget.limit_for(source)
    total_remaining = meter.remaining_total(budget)
    if source_limit is None and total_remaining is None:
        return None, "under_budget"
    if source_limit is None:
        return total_remaining, "max_total_tokens"
    if total_remaining is None:
        return source_limit, f"max_{source}_tokens"
    if total_remaining <= source_limit:
        return total_remaining, "max_total_tokens"
    return source_limit, f"max_{source}_tokens"


def _slice_utf8(text: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    return text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
