"""Measure decision routing against the lexical router on a labelled set.

The set is split in half by a seeded hash of each item id. The abstain
threshold is calibrated on the dev half; every reported number comes from the
test half. A shuffled-label control checks that "abstained items carry more
error" is a property of the router and not of the arithmetic.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from pathlib import Path

from forum.decision_routing import DecisionRouter, calibrate_threshold
from forum.roster import Roster, load_default
from forum.routing import LexicalRouter

SEED = 20261003


def split(items: list[dict], seed: int = SEED) -> tuple[list[dict], list[dict]]:
    dev, test = [], []
    for item in items:
        digest = hashlib.sha256(f"{seed}:{item['id']}".encode()).digest()
        (dev if digest[0] % 2 == 0 else test).append(item)
    return dev, test


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - h) / d, 3), round((c + h) / d, 3)]


def _rate(k: int, n: int) -> float:
    return round(k / n, 4) if n else 0.0


def abstain_stats(rows: list[tuple[str, str | None, str]]) -> dict:
    """rows: (top-1 lane, decided lane or None, gold). Error is top-1 vs gold."""
    dec = [r for r in rows if r[1] is not None]
    abst = [r for r in rows if r[1] is None]
    dec_err = sum(1 for top, _, gold in dec if top != gold)
    abs_err = sum(1 for top, _, gold in abst if top != gold)
    dec_rate, abs_rate = _rate(dec_err, len(dec)), _rate(abs_err, len(abst))
    # None when decided items carry no error: the ratio is undefined, not infinite
    ratio = round(abs_rate / dec_rate, 3) if dec_rate else None
    return {"decided": len(dec), "abstained": len(abst),
            "abstain_rate": _rate(len(abst), len(rows)),
            "decided_error_rate": dec_rate, "abstained_error_rate": abs_rate,
            "error_ratio": ratio}


def _arm(router, items: list[dict], roster: Roster) -> tuple[dict, list[tuple]]:
    rows = []
    for item in items:
        r = router.score(item["text"], roster)
        rows.append((r.candidates[0].agent, r.decided, item["gold"]))
    correct = sum(1 for top, _, gold in rows if top == gold)
    out = {"top1_accuracy": _rate(correct, len(rows)),
           "top1_wilson": wilson(correct, len(rows)), **abstain_stats(rows)}
    return out, rows


def run(items: list[dict], roster: Roster | None = None, seed: int = SEED) -> dict:
    roster = roster or load_default()
    dev, test = split(items, seed)
    threshold = calibrate_threshold(DecisionRouter(), dev, roster)
    decision, rows = _arm(DecisionRouter(threshold=threshold), test, roster)
    lexical, _ = _arm(LexicalRouter(), test, roster)
    golds = [g for _, _, g in rows]
    random.Random(seed).shuffle(golds)
    shuffled = abstain_stats([(t, d, g) for (t, d, _), g in zip(rows, golds)])
    bar = {"A1_accuracy": decision["top1_accuracy"] >= lexical["top1_accuracy"],
           "A2_abstain_under_15pct": decision["abstain_rate"] < 0.15,
           "A3_error_ratio_at_least_2": (decision["error_ratio"] or 0.0) >= 2.0,
           "control_fails_A3": (shuffled["error_ratio"] or 0.0) < 2.0}
    return {"schema": "forum.decision-routing-bench/1", "seed": seed,
            "dev": len(dev), "test": len(test), "threshold": threshold,
            "decision": decision, "lexical": lexical,
            "shuffled_label_control": shuffled, "bar": bar}


def main(argv: list[str] | None = None) -> int:
    import sys
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m forum.decision_routing_bench LABELS.json", file=sys.stderr)
        return 2
    items = json.loads(Path(args[0]).read_text(encoding="utf-8"))["items"]
    print(json.dumps(run(items), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
