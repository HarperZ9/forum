from __future__ import annotations

import json
import os
from typing import Any

from forum.ledger import LedgerEntry


_ENTRY_FIELDS = (
    "seq", "ts", "actor", "kind",
    "causal_parent", "payload_hash", "prev_hash", "entry_hash",
)


class StorageCorruption(ValueError):
    """A persisted log line is malformed in a way a crash cannot explain."""


def _entry_to_row(e: LedgerEntry) -> dict[str, Any]:
    return {
        "seq": e.seq,
        "ts": e.ts,
        "actor": e.actor,
        "kind": e.kind,
        "causal_parent": e.causal_parent,
        "payload_hash": e.payload_hash,
        "prev_hash": e.prev_hash,
        "entry_hash": e.entry_hash,
    }


def _row_to_entry(row: dict[str, Any]) -> LedgerEntry:
    for field in _ENTRY_FIELDS:
        if field not in row:
            raise StorageCorruption(f"entry row missing field: {field!r}")
    return LedgerEntry(
        seq=row["seq"],
        ts=row["ts"],
        actor=row["actor"],
        kind=row["kind"],
        causal_parent=row["causal_parent"],
        payload_hash=row["payload_hash"],
        prev_hash=row["prev_hash"],
        entry_hash=row["entry_hash"],
    )


def _read_rows(path: str) -> list[dict[str, Any]]:
    """Parse a JSONL file into rows, tolerating one torn trailing line.

    An interior unparseable line is corruption and raises StorageCorruption;
    only the final line may be a half-written (crash-truncated) append, which
    is dropped. Trailing truncation of whole, complete lines is not
    self-detectable (any prefix of an append-only chain is itself valid);
    detect it by comparing checkpoint() against an external witness.
    """
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    rows: list[dict[str, Any]] = []
    last = len(lines) - 1
    for i, line in enumerate(lines):
        if not line:
            if i == last:
                continue  # trailing blank line
            raise StorageCorruption(f"{path}: blank line at row {i}")
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            if i == last:
                break  # torn final append: drop it, keep the rest
            raise StorageCorruption(f"{path}: corrupt line at row {i}") from exc
    return rows


def _append_line(path: str, row: dict[str, Any]) -> None:
    line = json.dumps(row, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


class FileStorage:
    """Durable append-only storage for a Ledger, backed by two JSONL logs.

    Layout under ``directory``:
      entries.jsonl   one row per LedgerEntry, in append (seq) order
      payloads.jsonl  one {"hash", "body"} row per distinct payload

    Both logs are read into memory on construction; reads are served from
    memory and every append is mirrored to memory and flushed + fsynced to
    disk, so a fresh FileStorage over the same directory recovers the exact
    ledger after a restart. Payload bodies must be JSON-serializable; the
    ledger's payloads (plain dicts) already are.

    Corruption is surfaced, not hidden: an interior line that is unparseable,
    blank, or missing a required field raises StorageCorruption; only a single
    torn trailing line (a crash-cut final append) is tolerated and dropped.
    """

    def __init__(self, directory: str) -> None:
        os.makedirs(directory, exist_ok=True)
        self._entries_path = os.path.join(directory, "entries.jsonl")
        self._payloads_path = os.path.join(directory, "payloads.jsonl")
        self._entries: list[LedgerEntry] = [
            _row_to_entry(r) for r in _read_rows(self._entries_path)
        ]
        self._payloads: dict[str, Any] = {}
        for r in _read_rows(self._payloads_path):
            if "hash" not in r or "body" not in r:
                raise StorageCorruption("payload row missing 'hash' or 'body'")
            self._payloads.setdefault(r["hash"], r["body"])

    def append(self, entry: LedgerEntry) -> None:
        _append_line(self._entries_path, _entry_to_row(entry))
        self._entries.append(entry)

    def all(self) -> list[LedgerEntry]:
        return list(self._entries)

    def head(self) -> LedgerEntry | None:
        return self._entries[-1] if self._entries else None

    def get(self, seq: int) -> LedgerEntry:
        if seq < 0 or seq >= len(self._entries):
            raise KeyError(seq)
        entry = self._entries[seq]
        if entry.seq != seq:
            raise KeyError(seq)
        return entry

    def count(self) -> int:
        return len(self._entries)

    def put_payload(self, payload_hash: str, body: Any) -> None:
        if payload_hash in self._payloads:
            return
        _append_line(self._payloads_path, {"hash": payload_hash, "body": body})
        self._payloads[payload_hash] = body

    def get_payload(self, payload_hash: str) -> Any:
        return self._payloads[payload_hash]
