#!/usr/bin/env python3
"""verify_ledger.py -- a standalone verifier for a forum gradable-trajectory
export. Python standard library only, no forum package. A stranger holding one
exported ``forum.gradable-trajectory/1`` JSONL file re-derives its hash chain
offline:  ``python verify_ledger.py gradable.jsonl``

For each row it re-checks the row seal, re-derives every entry_hash from its
fields with sha256, links the chain from genesis, folds the RFC6962 merkle root
over the entry hashes against ``oracle.merkle_root``, then confirms each shipped
check-payload body hashes to a witnessed entry. It prints one line and exits 0
only on MATCH.

Scope (honest null): this re-derives the chain, the merkle root, the row seal,
and the binding of every shipped check-payload body. It does not re-run the
trajectory or re-hash payload bodies the export omitted; that fuller clause is
forum's ``oracle.verified`` self-report, which this verifier neither reads nor
trusts. A tamper of any shipped entry field still breaks its entry_hash recompute.

Exit: 0 MATCH, 1 DRIFT (a chain, merkle, or seal mismatch), 2 UNVERIFIABLE (missing/unreadable).
"""
import hashlib
import json
import pathlib
import sys

GENESIS = "0" * 64
_SEP = "\x1f"

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _entry_hash(e: dict) -> str:
    cp = "" if e.get("causal_parent") is None else str(e["causal_parent"])
    parts = [str(e["seq"]), f'{e["ts"]:.6f}', e["actor"], e["kind"], cp,
             e["payload_hash"], e["prev_hash"]]
    return _sha(_SEP.join(parts).encode("utf-8"))

def _leaf(h: str) -> str:
    return _sha(b"\x00" + h.encode("utf-8"))

def _node(left: str, right: str) -> str:
    return _sha(b"\x01" + left.encode("utf-8") + right.encode("utf-8"))

def _merkle_root(hashes: list) -> str:
    """RFC6962-style root: 0x00 leaf, 0x01 node, a lone odd node promoted."""
    if not hashes:
        return GENESIS
    level = [_leaf(h) for h in hashes]
    while len(level) > 1:
        level = [_node(level[i], level[i + 1]) if i + 1 < len(level) else level[i]
                 for i in range(0, len(level), 2)]
    return level[0]

def _canonical_hash(body) -> str:
    data = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return _sha(data.encode("utf-8"))

def _row_seal(row: dict) -> str:
    body = {k: v for k, v in row.items() if k != "row_hash"}
    return _sha(json.dumps(body, sort_keys=True).encode())[:16]

def verify_row(row: dict):
    """Re-derive one exported row. Returns (ok: bool, detail: str)."""
    seal = row.get("row_hash")
    if seal is not None and _row_seal(row) != seal:
        return False, "row seal does not re-derive (row tampered or corrupted)"
    entries = row.get("trajectory", {}).get("entries", [])
    prev = GENESIS
    for i, e in enumerate(entries):
        if e.get("seq") != i:
            return False, f"seq {e.get('seq')} out of order at position {i}"
        if e.get("prev_hash") != prev:
            return False, f"entry {e.get('seq')} chain broken: prev_hash != prior entry_hash"
        if _entry_hash(e) != e.get("entry_hash"):
            return False, f"entry {e.get('seq')} field tampered: entry_hash does not re-derive"
        prev = e["entry_hash"]
    oracle = row.get("oracle", {})
    if _merkle_root([e["entry_hash"] for e in entries]) != oracle.get("merkle_root"):
        return False, "merkle root does not re-derive over the entry chain"
    witnessed = {e["payload_hash"] for e in entries}
    for cp in oracle.get("check_payloads", []):
        ph = cp.get("payload_hash")
        if ph not in witnessed:
            return False, f"check payload seq {cp.get('seq')} is not bound to a witnessed entry"
        if _canonical_hash(cp.get("body")) != ph:
            return False, f"check payload seq {cp.get('seq')} body does not hash to its payload_hash"
    return True, "chain, merkle root, seal, and bound checks re-derive"

def main(argv: list) -> int:
    if not argv:
        print("UNVERIFIABLE  usage: python verify_ledger.py <gradable.jsonl>")
        return 2
    try:
        text = pathlib.Path(argv[0]).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"UNVERIFIABLE  cannot read artifact: {exc}")
        return 2
    rows = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError as exc:
            print(f"UNVERIFIABLE  artifact line {lineno} is not valid JSON: {exc}")
            return 2
    if not rows:
        print("UNVERIFIABLE  artifact holds no ledger rows")
        return 2
    for i, row in enumerate(rows):
        ok, detail = verify_row(row)
        if not ok:
            print(f"DRIFT  row {i} ({row.get('task_id')}): {detail}")
            return 1
    print(f"MATCH  {len(rows)} row(s) re-derived: chain, merkle root, seal, bound checks")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
