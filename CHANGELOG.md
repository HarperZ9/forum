# Changelog

## 0.1.0: core foundation

The accountable core, pure standard library, zero runtime dependencies.

- **Ledger**: append-only hash chain with a content-addressed payload store:
  `verify()` (chain integrity), `verify(deep=True)` (re-checks payload bodies,
  tolerates redacted/hash-only), `replay()`, `query()`, `causal_chain()`, and a
  domain-separated Merkle `checkpoint()` that resists the CVE-2012-2459 odd-node
  second-preimage collision. Fail-fast on out-of-range lookups; cycle-guarded
  causal walks.
- **Routing**: deterministic, specificity-aware `LexicalRouter` (Tier-0): decides a
  lane or escalates with a confidence score; total-ordered, roster-order-independent.
- **Roster**: validated TOML capability-manifest loader (rejects non-list keywords,
  unknown tiers, missing fields).
- **Plan**: DAG scheduler into ordered parallel waves; cycle and unknown-dependency
  detection.
- **Policy**: category scope gate and parallel-wave capping.

29 tests. Runnable tour in `examples/demo.py`.
