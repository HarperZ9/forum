from __future__ import annotations

import json
import platform
import statistics
import sys
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from forum.ledger import InMemoryStorage, Ledger, LedgerEntry, Storage
from forum.storage import FileStorage

SCHEMA = "forum.deep-verify-benchmark/v1"
STORAGE_MODES = ("memory", "file-sync", "file-batched")


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    entry_count: int
    payload_body_bytes: int
    storage_mode: str
    redaction_ratio: float


def parse_int_csv(text: str) -> list[int]:
    values: list[int] = []
    for raw in text.split(","):
        raw = raw.strip()
        if not raw:
            continue
        value = int(raw)
        if value < 0:
            raise ValueError("integer lists cannot contain negative values")
        values.append(value)
    if not values:
        raise ValueError("expected at least one integer")
    return values


def parse_float_csv(text: str) -> list[float]:
    values: list[float] = []
    for raw in text.split(","):
        raw = raw.strip()
        if not raw:
            continue
        value = float(raw)
        if value < 0.0 or value > 1.0:
            raise ValueError("redaction ratios must be between 0 and 1")
        values.append(value)
    if not values:
        raise ValueError("expected at least one ratio")
    return values


def benchmark_matrix(
    *,
    entry_counts: Iterable[int],
    payload_body_bytes: Iterable[int],
    storage_modes: Iterable[str],
    redaction_ratios: Iterable[float],
    repeats: int,
    warmups: int,
) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    if warmups < 0:
        raise ValueError("warmups must be >= 0")
    entry_counts = list(entry_counts)
    payload_body_bytes = list(payload_body_bytes)
    storage_modes = list(storage_modes)
    redaction_ratios = list(redaction_ratios)

    cases = [
        BenchmarkCase(count, size, mode, ratio)
        for count in entry_counts
        for size in payload_body_bytes
        for mode in storage_modes
        for ratio in redaction_ratios
    ]
    results = [_run_case(case, repeats=repeats, warmups=warmups) for case in cases]
    return {
        "schema": SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "parameters": {
            "entry_counts": entry_counts,
            "payload_body_bytes": payload_body_bytes,
            "storage_modes": storage_modes,
            "redaction_ratios": redaction_ratios,
            "repeats": repeats,
            "warmups": warmups,
        },
        "cases": results,
    }


def report_text(payload: dict[str, Any]) -> str:
    lines = [
        "Forum deep-verify benchmark",
        f"schema: {payload['schema']}",
        f"python: {payload['python']} | platform: {payload['platform']}",
        "",
        (
            f"{'entries':>8} {'body':>8} {'storage':<12} {'redact':>7} "
            f"{'build_ms':>10} {'chain_ms':>10} {'payload_ms':>11} {'deep_ms':>10}"
        ),
    ]
    for case in payload["cases"]:
        lines.append(
            f"{case['entry_count']:>8} "
            f"{case['payload_body_bytes']:>8} "
            f"{case['storage_mode']:<12} "
            f"{case['redaction_ratio']:>7.2f} "
            f"{case['build']['ms']:>10.3f} "
            f"{case['verify_chain']['mean_ms']:>10.3f} "
            f"{case['verify_payloads']['mean_ms']:>11.3f} "
            f"{case['verify_deep']['mean_ms']:>10.3f}"
        )
    return "\n".join(lines)


def _run_case(case: BenchmarkCase, *, repeats: int, warmups: int) -> dict[str, Any]:
    start = time.perf_counter_ns()
    with _storage(case.storage_mode) as storage:
        ledger = Ledger(storage, clock=_monotonic_clock())
        for seq in range(case.entry_count):
            ledger.append(
                actor="bench",
                kind="payload",
                payload=_payload(seq, case.payload_body_bytes),
                causal_parent=None if seq == 0 else seq - 1,
            )
        ledger.sync()
        build_ms = _elapsed_ms(start)
        entries = ledger.replay()
        redacted = _redact_payloads(storage, entries, case.redaction_ratio)

        for _ in range(warmups):
            ledger.verify()
            ledger.verify_payloads()
            ledger.verify(deep=True)

        chain = _time_repeated(ledger.verify, repeats)
        payloads = _time_repeated(ledger.verify_payloads, repeats)
        deep = _time_repeated(lambda: ledger.verify(deep=True), repeats)

        unique_payloads = len({entry.payload_hash for entry in entries})
        return {
            "entry_count": case.entry_count,
            "payload_body_bytes": case.payload_body_bytes,
            "storage_mode": case.storage_mode,
            "fsync_each": _fsync_each(case.storage_mode),
            "redaction_ratio": case.redaction_ratio,
            "unique_payloads": unique_payloads,
            "payloads_present": unique_payloads - redacted,
            "payloads_redacted": redacted,
            "build": {"ms": build_ms},
            "verify_chain": chain,
            "verify_payloads": payloads,
            "verify_deep": deep,
        }


def _payload(seq: int, payload_body_bytes: int) -> dict[str, str]:
    prefix = f"{seq:016d}:"
    fill = "x" * max(0, payload_body_bytes - len(prefix))
    return {"body": prefix + fill}


def _redact_payloads(storage: Storage, entries: list[LedgerEntry], ratio: float) -> int:
    if ratio <= 0.0:
        return 0
    hashes = sorted({entry.payload_hash for entry in entries})
    count = int(len(hashes) * ratio)
    payloads = getattr(storage, "_payloads", None)
    if not isinstance(payloads, dict):
        return 0
    for payload_hash in hashes[:count]:
        payloads.pop(payload_hash, None)
    return count


def _time_repeated(fn, repeats: int) -> dict[str, Any]:
    samples: list[float] = []
    result = None
    for _ in range(repeats):
        start = time.perf_counter_ns()
        result = fn()
        samples.append(_elapsed_ms(start))
    return {
        "ok": bool(result),
        "samples_ms": samples,
        "mean_ms": statistics.fmean(samples),
        "min_ms": min(samples),
        "max_ms": max(samples),
    }


def _elapsed_ms(start_ns: int) -> float:
    return (time.perf_counter_ns() - start_ns) / 1_000_000.0


def _monotonic_clock():
    tick = 0

    def clock() -> float:
        nonlocal tick
        tick += 1
        return float(tick)

    return clock


def _fsync_each(storage_mode: str) -> bool | None:
    if storage_mode == "memory":
        return None
    if storage_mode == "file-sync":
        return True
    if storage_mode == "file-batched":
        return False
    raise ValueError(f"unknown storage mode: {storage_mode}")


class _storage:
    def __init__(self, mode: str) -> None:
        if mode not in STORAGE_MODES:
            raise ValueError(f"unknown storage mode: {mode}")
        self._mode = mode
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self.storage: Storage | None = None

    def __enter__(self) -> Storage:
        if self._mode == "memory":
            self.storage = InMemoryStorage()
            return self.storage
        self._tmp = tempfile.TemporaryDirectory(prefix="forum-deep-verify-")
        fsync_each = _fsync_each(self._mode)
        if fsync_each is None:
            raise ValueError(f"file storage needs an fsync policy: {self._mode}")
        self.storage = FileStorage(self._tmp.name, fsync_each=fsync_each)
        return self.storage

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)
