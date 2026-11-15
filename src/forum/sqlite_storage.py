from __future__ import annotations

import json
import os
import random
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

from forum.ledger import LedgerEntry, SeqCollision
from forum.storage import StorageBusy, StorageCorruption

_T = TypeVar("_T")

DEFAULT_LOCK_TIMEOUT = 30.0
"""Seconds a call waits for a lock held by another connection before StorageBusy."""

# A waiter asks again after a short, jittered pause. SQLite's own busy handler
# backs off to 100 ms sleeps, and a writer in a loop takes the lock back within
# microseconds of releasing it, so waiters on that handler starve behind it.
# Asking every few milliseconds lets them in between two of its appends.
_POLL_MIN = 0.0005
_POLL_MAX = 0.004
_CHECKPOINT_WAIT = 5.0
_SQLITE_BUSY = 5
_SQLITE_LOCKED = 6


def _is_lock_error(exc: sqlite3.OperationalError) -> bool:
    return (exc.sqlite_errorcode & 0xFF) in (_SQLITE_BUSY, _SQLITE_LOCKED)

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

    Writers take turns. Every write runs inside a transaction that takes the
    write lock first (``BEGIN IMMEDIATE``), and ``Ledger.append`` reads the
    head, stores the payload and inserts the entry inside one such transaction,
    so an append lands whole or leaves nothing behind. A writer that finds the
    lock held asks again every few milliseconds for up to ``lock_timeout``
    seconds (default 30) and then raises ``StorageBusy``; it never writes a
    partial append and never reports a held lock as corruption. The wait blocks
    the calling thread.

    Durability is tunable, matching ``FileStorage``. By default
    (``fsync_each=True``) every write is committed with ``synchronous=FULL``, the
    strongest guarantee. With ``fsync_each=False`` writes accumulate in one
    transaction (``synchronous=NORMAL``) and become durable when you call
    ``sync()`` — trading a crash window for far higher append throughput.
    A batched writer keeps the write lock from its first write until ``sync()``
    or ``close()``, so batched mode suits one writer at a time: a second writer
    waits for that sync and raises ``StorageBusy`` at its bound.
    Payload bodies must be JSON-serializable, exactly as for ``FileStorage``.
    """

    def __init__(
        self,
        path: str,
        *,
        fsync_each: bool = True,
        lock_timeout: float = DEFAULT_LOCK_TIMEOUT,
    ) -> None:
        if lock_timeout < 0:
            raise ValueError("lock_timeout must be zero or more seconds")
        self._path = path
        self._fsync_each = fsync_each
        self._lock_timeout = float(lock_timeout)
        self._in_txn = False
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        try:
            # isolation_level=None -> we control transactions explicitly.
            self._conn = sqlite3.connect(path, isolation_level=None)
            # SQLite's own wait is off: _retry_locked does the waiting, with
            # short pauses and one wall-clock bound for every kind of call.
            self._conn.execute("PRAGMA busy_timeout=0")
            # Two workers opening a new file together both ask for the lock that
            # switching to WAL and creating the tables need; the loser waits.
            self._retry_locked(self._open_schema, "lock that opening the database needs")
        except sqlite3.DatabaseError as exc:  # not a valid SQLite file
            raise StorageCorruption(f"{path}: not a valid SQLite database") from exc
        self._validate_schema()

    def _open_schema(self) -> None:
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            f"PRAGMA synchronous={'FULL' if self._fsync_each else 'NORMAL'}"
        )
        self._conn.executescript(_SCHEMA)

    def _retry_locked(self, op: Callable[[], _T], what: str) -> _T:
        """Run ``op``; while another connection holds the lock, wait and retry.

        Only calls that have written nothing are retried (taking the write
        lock, reads, opening), so a retry can never repeat or split a write.
        Raises ``StorageBusy`` once ``lock_timeout`` seconds have passed.
        """
        started = time.monotonic()
        attempts = 0
        delay = _POLL_MIN
        while True:
            attempts += 1
            try:
                return op()
            except sqlite3.OperationalError as exc:
                if not _is_lock_error(exc):
                    raise
                waited = time.monotonic() - started
                if waited >= self._lock_timeout:
                    raise StorageBusy(self._path, what, waited, attempts) from exc
                pause = delay * (0.5 + random.random())
                time.sleep(min(pause, self._lock_timeout - waited))
                delay = min(delay * 2, _POLL_MAX)

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        return self._retry_locked(
            lambda: self._conn.execute(sql, params).fetchall(), "read lock"
        )

    def _validate_schema(self) -> None:
        cols = {r[1] for r in self._query("PRAGMA table_info(entries)")}
        expected = {
            "seq", "ts", "actor", "kind",
            "causal_parent", "payload_hash", "prev_hash", "entry_hash",
        }
        if not expected.issubset(cols):
            raise StorageCorruption(
                f"{self._path}: entries table missing columns "
                f"{sorted(expected - cols)!r}"
            )

    def _commit(self) -> None:
        if self._in_txn:
            self._conn.execute("COMMIT")
            self._in_txn = False

    @contextmanager
    def write_transaction(self) -> Iterator[None]:
        """Hold the write lock across one unit of work.

        The lock is taken before anything is read or written, so what the
        caller reads inside the block (the head) cannot change before its
        writes land. In the default mode the unit commits on a clean exit and
        rolls back on an error. In batched mode the transaction stays open
        until ``sync()`` or ``close()``. Nested use joins the open transaction.
        """
        if self._in_txn:
            yield
            return
        self._retry_locked(lambda: self._conn.execute("BEGIN IMMEDIATE"), "write lock")
        self._in_txn = True
        if not self._fsync_each:
            yield
            return
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            self._in_txn = False
            raise
        self._commit()

    def append(self, entry: LedgerEntry) -> None:
        with self.write_transaction():
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
                # seq is the PRIMARY KEY: a duplicate means another writer
                # claimed this seq first. Surface it as a retryable race, not
                # corruption, so the Ledger re-reads head and tries again.
                raise SeqCollision(f"seq {entry.seq} already present") from exc

    def all(self) -> list[LedgerEntry]:
        rows = self._query(f"SELECT {_COLS} FROM entries ORDER BY seq")
        return [_row_to_entry(r) for r in rows]

    def head(self) -> LedgerEntry | None:
        rows = self._query(f"SELECT {_COLS} FROM entries ORDER BY seq DESC LIMIT 1")
        return _row_to_entry(rows[0]) if rows else None

    def get(self, seq: int) -> LedgerEntry:
        if seq < 0:
            raise KeyError(seq)
        rows = self._query(f"SELECT {_COLS} FROM entries WHERE seq = ?", (seq,))
        if not rows:
            raise KeyError(seq)
        return _row_to_entry(rows[0])

    def count(self) -> int:
        # seq is dense and 0-based (the Ledger assigns 0,1,2,...), so the entry
        # count is max(seq)+1 — an O(log n) index probe, not an O(n) COUNT(*).
        rows = self._query("SELECT COALESCE(MAX(seq), -1) + 1 FROM entries")
        return int(rows[0][0])

    def put_payload(self, payload_hash: str, body: Any) -> None:
        with self.write_transaction():
            # OR IGNORE keeps the first body written for a hash (setdefault
            # semantics), matching InMemoryStorage and FileStorage.
            self._conn.execute(
                "INSERT OR IGNORE INTO payloads (payload_hash, body) VALUES (?, ?)",
                (payload_hash, json.dumps(body, ensure_ascii=False)),
            )

    def get_payload(self, payload_hash: str) -> Any:
        rows = self._query(
            "SELECT body FROM payloads WHERE payload_hash = ?", (payload_hash,)
        )
        if not rows:
            raise KeyError(payload_hash)
        return json.loads(rows[0][0])

    def sync(self) -> None:
        """Force buffered appends to durable storage.

        In the default mode (``fsync_each=True``) each write is already durable,
        so this is a redundant checkpoint. In batched mode (``fsync_each=False``)
        it commits the open transaction and checkpoints the WAL into the main
        database file, which is how you make a batch of appends durable at a
        chosen point (a phase boundary or run end). A checkpoint that other
        connections block is asked again for up to five seconds (or
        ``lock_timeout`` when that is shorter), the wait SQLite itself made
        before this storage did its own waiting; a later checkpoint finishes it.
        """
        self._commit()
        started = time.monotonic()
        limit = min(_CHECKPOINT_WAIT, self._lock_timeout)
        while True:
            try:
                row = self._conn.execute("PRAGMA wal_checkpoint(FULL)").fetchone()
            except sqlite3.OperationalError as exc:
                if not _is_lock_error(exc):
                    raise
                row = (1,)
            if not row or not row[0] or time.monotonic() - started >= limit:
                return
            time.sleep(_POLL_MAX)

    def close(self) -> None:
        """Commit any open batch and close the database connection."""
        self._commit()
        self._conn.close()
