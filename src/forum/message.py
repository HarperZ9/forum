from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from forum.hashing import canonical_hash

# Allowed envelope kinds.
KINDS = frozenset(
    {"request", "route", "plan", "task", "handoff", "verdict", "result"}
)


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    kind: str
    sender: str
    payload: Any
    causal_parent: str | None
    payload_hash: str


def new_message(
    kind: str,
    sender: str,
    payload: Any,
    *,
    id: str,
    causal_parent: str | None = None,
) -> Message:
    if kind not in KINDS:
        raise ValueError(f"unknown message kind: {kind!r}")
    return Message(
        id=id,
        kind=kind,
        sender=sender,
        payload=payload,
        causal_parent=causal_parent,
        payload_hash=canonical_hash(payload),
    )
