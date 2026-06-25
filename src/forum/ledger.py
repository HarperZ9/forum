from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any, Protocol

from forum.hashing import canonical_hash

GENESIS = "0" * 64
_SEP = "\x1f"


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    seq: int
    ts: float
    actor: str
    kind: str
    causal_parent: int | None
    payload_hash: str
    prev_hash: str
    entry_hash: str


def compute_entry_hash(
    seq: int,
    ts: float,
    actor: str,
    kind: str,
    causal_parent: int | None,
    payload_hash: str,
    prev_hash: str,
) -> str:
    parts = [
        str(seq),
        f"{ts:.6f}",
        actor,
        kind,
        "" if causal_parent is None else str(causal_parent),
        payload_hash,
        prev_hash,
    ]
    return hashlib.sha256(_SEP.join(parts).encode("utf-8")).hexdigest()


def _leaf_hash(h: str) -> str:
    return hashlib.sha256(b"\x00" + h.encode("utf-8")).hexdigest()


def _node_hash(left: str, right: str) -> str:
    return hashlib.sha256(b"\x01" + left.encode("utf-8") + right.encode("utf-8")).hexdigest()


def merkle_root(hashes: list[str]) -> str:
    """Domain-separated binary Merkle root (RFC 6962 style). Empty -> GENESIS.

    Leaves are tagged 0x00, internal nodes 0x01, and a lone odd node is
    promoted up unchanged (never duplicated), so two different leaf sets such
    as [a,b,c] and [a,b,c,c] cannot collide (CVE-2012-2459). Order-sensitive.
    """
    if not hashes:
        return GENESIS
    level = [_leaf_hash(h) for h in hashes]
    while len(level) > 1:
        nxt: list[str] = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                nxt.append(_node_hash(level[i], level[i + 1]))
            else:
                nxt.append(level[i])  # promote lone node unchanged
        level = nxt
    return level[0]


class Storage(Protocol):
    def append(self, entry: LedgerEntry) -> None: ...
    def all(self) -> list[LedgerEntry]:
        """Return a fresh list of all entries in seq order; the caller may mutate it."""
        ...
    def head(self) -> LedgerEntry | None: ...
    def get(self, seq: int) -> LedgerEntry: ...
    def put_payload(self, payload_hash: str, body: Any) -> None: ...
    def get_payload(self, payload_hash: str) -> Any: ...


class InMemoryStorage:
    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []
        self._payloads: dict[str, Any] = {}

    def append(self, entry: LedgerEntry) -> None:
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
        self._payloads.setdefault(payload_hash, body)

    def get_payload(self, payload_hash: str) -> Any:
        return self._payloads[payload_hash]


class Ledger:
    def __init__(self, storage: Storage, clock=time.time) -> None:
        self._s = storage
        self._clock = clock

    def append(
        self,
        *,
        actor: str,
        kind: str,
        payload: Any,
        causal_parent: int | None = None,
    ) -> LedgerEntry:
        # INVARIANT: append must stay await-free. Concurrent async callers (for
        # example dispatch_plan's TaskGroup) rely on this method being atomic
        # under cooperative scheduling; an await between reading head() and the
        # append would corrupt seq/prev_hash linkage. Do not introduce awaits here.
        head = self._s.head()
        seq = 0 if head is None else head.seq + 1
        prev = GENESIS if head is None else head.entry_hash
        payload_hash = canonical_hash(payload)
        self._s.put_payload(payload_hash, payload)
        ts = float(self._clock())
        entry_hash = compute_entry_hash(
            seq, ts, actor, kind, causal_parent, payload_hash, prev
        )
        entry = LedgerEntry(
            seq, ts, actor, kind, causal_parent, payload_hash, prev, entry_hash
        )
        self._s.append(entry)
        return entry

    def verify(self, *, deep: bool = False) -> bool:
        prev = GENESIS
        for i, e in enumerate(self._s.all()):
            if e.seq != i or e.prev_hash != prev:
                return False
            recomputed = compute_entry_hash(
                e.seq, e.ts, e.actor, e.kind, e.causal_parent, e.payload_hash, e.prev_hash
            )
            if recomputed != e.entry_hash:
                return False
            prev = e.entry_hash
        if deep and not self.verify_payloads():
            return False
        return True

    def verify_payloads(self) -> bool:
        """Verify each stored payload body still hashes to its content key.

        Absent payloads (redacted / hash-only storage) are permitted and
        skipped, preserving the documented hash-only mode.
        """
        for e in self._s.all():
            try:
                body = self._s.get_payload(e.payload_hash)
            except KeyError:
                continue
            if canonical_hash(body) != e.payload_hash:
                return False
        return True

    def get(self, seq: int) -> LedgerEntry:
        """Return the entry at seq, or raise KeyError if absent."""
        return self._s.get(seq)

    def replay(self, until: int | None = None) -> list[LedgerEntry]:
        entries = self._s.all()
        if until is None:
            return entries
        return [e for e in entries if e.seq <= until]

    def query(
        self, *, kind: str | None = None, actor: str | None = None
    ) -> list[LedgerEntry]:
        out = self._s.all()
        if kind is not None:
            out = [e for e in out if e.kind == kind]
        if actor is not None:
            out = [e for e in out if e.actor == actor]
        return out

    def causal_chain(self, seq: int) -> list[LedgerEntry]:
        chain: list[LedgerEntry] = []
        seen: set[int] = set()
        cursor: int | None = seq
        while cursor is not None:
            if cursor in seen:
                raise ValueError(f"causal cycle detected at seq {cursor}")
            seen.add(cursor)
            entry = self._s.get(cursor)
            chain.append(entry)
            cursor = entry.causal_parent
        chain.reverse()
        return chain

    def checkpoint(self) -> str:
        return merkle_root([e.entry_hash for e in self._s.all()])
