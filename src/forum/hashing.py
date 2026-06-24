from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_hash(payload: Any) -> str:
    """Deterministic SHA-256 (hex) over a JSON-canonicalized payload.

    Keys are sorted and whitespace removed so logically-equal payloads hash
    identically. Non-JSON values fall back to ``str``.
    """
    data = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()
