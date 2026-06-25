from __future__ import annotations

import json
import os
from typing import Any

from forum.ledger import LedgerEntry


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
    """Strict JSONL read: every non-blank line must parse. (Task 2 relaxes this.)"""
    if not os.path.exists(path):
        return []
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
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

    def put_payload(self, payload_hash: str, body: Any) -> None:
        if payload_hash in self._payloads:
            return
        _append_line(self._payloads_path, {"hash": payload_hash, "body": body})
        self._payloads[payload_hash] = body

    def get_payload(self, payload_hash: str) -> Any:
        return self._payloads[payload_hash]
