from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from forum.ledger import LedgerEntry, SeqCollision
from forum.storage import StorageCorruption

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    seq           INTEGER PRIMARY KEY,
    ts            REAL    NOT NULL,
    actor         TEXT    NOT NULL,
    kind          TEXT    NOT NULL,
    causal_parent INTEGER,
    payload_hash  TEXT    NOT NULL,
    prev_hash     TEXT    NOT NULL,
    entry_hash    TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS payloads (
    payload_hash TEXT PRIMARY KEY,
    body         TEXT NOT NULL
);
"""

_COLS = "seq, ts, actor, kind, causal_parent, payload_hash, prev_hash, entry_hash"


def _row_to_entry(row: tuple[Any, ...]) -> LedgerEntry:
    return LedgerEntry(
        seq=row[0],
        ts=row[1],
        actor=row[2],
        kind=row[3],
        causal_parent=row[4],
        payload_hash=row[5],
        prev_hash=row[6],
        entry_hash=row[7],
    )


class SqliteStorage:
    """Durable, RAM-free append-only storage for a Ledger, backed by SQLite.

    ``InMemoryStorage`` and ``FileStorage`` both hold the entire ledger and every
    payload resident in process memory (``FileStorage`` reads the whole log into
    RAM on construction). That is the ceiling this backend removes: the log lives
    on disk, and point reads (``head``/``get``/``count``/``get_payload``) are
    served by indexed queries that never materialize the whole ledger, so
    resident memory stays flat as the log grows into the millions of entries.
    Only ``all()`` — used by ``verify``/``checkpoint``/``replay``/``query`` —
    streams the full set, and only for the duration of that call.

    The database opens in WAL mode, so many concurrent readers and a single
    writer can share one file: the substrate a stateless multi-worker deployment
    is built on. Entry order and the ``seq`` linkage are unchanged, so the
    ledger's Merkle chain and every receipt verify byte-for-byte against the
    other backends.

    Durability is tunable, matching ``FileStorage``. By default
    (``fsync_each=True``) every write is committed with ``synchronous=FULL``, the
    strongest guarantee. With ``fsync_each=False`` writes accumulate in one
    transaction (``synchronous=NORMAL``) and become durable when you call
    ``sync()`` — trading a crash window for far higher append throughput.
    Payload bodies must be JSON-serializable, exactly as for ``FileStorage``.
    """

    def __init__(self, path: str, *, fsync_each: bool = True) -> None:
        self._path = path
        self._fsync_each = fsync_each
        self._in_txn = False
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        try:
            # isolation_level=None -> we control transactions explicitly; a bare
            # statement autocommits, which is what fsync_each=True relies on.
            self._conn = sqlite3.connect(path, isolation_level=None)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                f"PRAGMA synchronous={'FULL' if fsync_each else 'NORMAL'}"
            )
            # A concurrent writer holds the WAL write lock only briefly; wait for
            # it rather than failing fast, so multi-worker appends serialize
            # instead of erroring under contention.
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(_SCHEMA)
        except sqlite3.DatabaseError as exc:  # not a valid SQLite file
            raise StorageCorruption(f"{path}: not a valid SQLite database") from exc
        self._validate_schema()

    def _validate_schema(self) -> None:
        cols = {
            r[1]
            for r in self._conn.execute("PRAGMA table_info(entries)").fetchall()
        }
        expected = {
            "seq", "ts", "actor", "kind",
            "causal_parent", "payload_hash", "prev_hash", "entry_hash",
        }
        if not expected.issubset(cols):
            raise StorageCorruption(
                f"{self._path}: entries table missing columns "
                f"{sorted(expected - cols)!r}"
            )

    def _begin(self) -> None:
        if not self._fsync_each and not self._in_txn:
            self._conn.execute("BEGIN")
            self._in_txn = True

    def _commit(self) -> None:
        if self._in_txn:
            self._conn.execute("COMMIT")
            self._in_txn = False

    def append(self, entry: LedgerEntry) -> None:
        self._begin()
        try:
            self._conn.execute(
                f"INSERT INTO entries ({_COLS}) VALUES (?,?,?,?,?,?,?,?)",
                (
                    entry.seq, entry.ts, entry.actor, entry.kind,
                    entry.causal_parent, entry.payload_hash,
                    entry.prev_hash, entry.entry_hash,
                ),
            )
        except sqlite3.IntegrityError as exc:
            # seq is the PRIMARY KEY: a duplicate means a concurrent writer
            # claimed this seq first. Surface it as a retryable race, not
            # corruption, so the Ledger re-reads head and tries again.
            raise SeqCollision(f"seq {entry.seq} already present") from exc

    def all(self) -> list[LedgerEntry]:
        rows = self._conn.execute(
            f"SELECT {_COLS} FROM entries ORDER BY seq"
        ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def head(self) -> LedgerEntry | None:
        row = self._conn.execute(
            f"SELECT {_COLS} FROM entries ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return _row_to_entry(row) if row is not None else None

    def get(self, seq: int) -> LedgerEntry:
        if seq < 0:
            raise KeyError(seq)
        row = self._conn.execute(
            f"SELECT {_COLS} FROM entries WHERE seq = ?", (seq,)
        ).fetchone()
        if row is None:
            raise KeyError(seq)
        return _row_to_entry(row)

    def count(self) -> int:
        # seq is dense and 0-based (the Ledger assigns 0,1,2,...), so the entry
        # count is max(seq)+1 — an O(log n) index probe, not an O(n) COUNT(*).
        row = self._conn.execute(
            "SELECT COALESCE(MAX(seq), -1) + 1 FROM entries"
        ).fetchone()
        return int(row[0])

    def put_payload(self, payload_hash: str, body: Any) -> None:
        self._begin()
        # OR IGNORE keeps the first body written for a hash (setdefault semantics),
        # matching InMemoryStorage and FileStorage.
        self._conn.execute(
            "INSERT OR IGNORE INTO payloads (payload_hash, body) VALUES (?, ?)",
            (payload_hash, json.dumps(body, ensure_ascii=False)),
        )

    def get_payload(self, payload_hash: str) -> Any:
        row = self._conn.execute(
            "SELECT body FROM payloads WHERE payload_hash = ?", (payload_hash,)
        ).fetchone()
        if row is None:
            raise KeyError(payload_hash)
        return json.loads(row[0])

    def sync(self) -> None:
        """Force buffered appends to durable storage.

        In the default mode (``fsync_each=True``) each write is already durable,
        so this is a redundant checkpoint. In batched mode (``fsync_each=False``)
        it commits the open transaction and checkpoints the WAL into the main
        database file, which is how you make a batch of appends durable at a
        chosen point (a phase boundary or run end).
        """
        self._commit()
        self._conn.execute("PRAGMA wal_checkpoint(FULL)")

    def close(self) -> None:
        """Commit any open batch and close the database connection."""
        self._commit()
        self._conn.close()
