# Durable gate deadlines

A human-in-the-loop approval gate pauses a run at a wave boundary and waits for
an operator to approve, edit, or reject before the gated wave runs. By default a
gate waits forever: the run stays paused until a decision lands in the ledger.

A deadline makes the gate durable but bounded. It answers a real operational
question: what should happen if nobody shows up in time? The choice is witnessed
up front, so the run never stalls silently and never ships a wave without an
auditable decision.

## What it does

Attach a deadline to the gate policy:

```python
from forum.gates import GatePolicy

# pause wave 1; if no operator decides within 3600s of the gate being raised,
# auto-reject (the wave never runs). Use on_expiry="approve" to auto-approve.
gates = GatePolicy(
    frozenset({1}),
    "Approve the deploy wave?",
    deadline_seconds=3600,
    on_expiry="reject",   # default; the safe choice
)
```

When dispatch raises the gate it writes an absolute `deadline` and the chosen
`on_expiry` into the witnessed `gate_pending` entry. The deadline is anchored to
the ledger's own clock, so it is hashed into the ledger like every other field.

On a later resume, at the same wave boundary:

- If an operator has recorded a decision (`gate_approved` / `gate_edited` /
  `gate_rejected`), that decision wins. A deadline never overrides a real human.
- Else if the deadline has **not** passed, the gate is still `pending` and the
  run stays paused. Nothing downstream runs.
- Else if the deadline **has** passed, dispatch appends a witnessed
  `gate_expired` entry (hash-chained to the `gate_pending` it resolves) carrying
  `decision` = the policy's `on_expiry`, then acts on it: `approve` runs the
  gated wave, `reject` stops it with a `gate_stopped` entry.

## What it does NOT do

The deadline is evaluated **only when the run is resumed**, not by a background
timer. Forum does not spin up a clock thread that fires a decision while no one
is watching. This is deliberate: the auto-decision is a witnessed step in the
same resume path as every other gate outcome, so nothing runs behind the
operator's back between resumes. If you need the deadline to be enforced at a
wall-clock instant, drive `resume` on a schedule (for example a cron that calls
the run's resume path); the expiry then fires on the first resume after the
deadline.

`on_expiry` defaults to `reject` on purpose: an unattended gate that lapses does
not silently ship its wave unless you explicitly opted in with
`on_expiry="approve"`.

## Accountability

The feature rides on the existing witnessed causal ledger; it does not replace
it. Every path is a hash-chained entry:

- `gate_pending` carries `deadline` and `on_expiry`.
- `gate_expired` carries `decision`, `on_expiry`, and the `deadline` it passed,
  chained to the `gate_pending`.
- On auto-reject, `gate_stopped` is written exactly as for a manual reject.

The resumed run's ledger re-verifies end to end (`ledger.verify(deep=True)`),
including payload rehash, so a bounded gate leaves the same re-checkable record
as an unbounded one.

## Seeing the deadline

The deadline and its auto-decision are surfaced everywhere pending gates are
listed:

- CLI: `forum gate list` (text shows `[deadline=... on_expiry=...]`) and
  `forum gate list --json` (adds `deadline` and `on_expiry` fields).
- HTTP: `GET /gates` includes `deadline` and `on_expiry` per pending gate.
- MCP: `gate_list` proxies the same HTTP payload, so it inherits the fields.

Unbounded gates omit both fields, so existing tooling and callers are
unaffected.
