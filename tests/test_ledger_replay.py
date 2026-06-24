from forum.ledger import InMemoryStorage, Ledger, merkle_root


def build():
    ticks = iter([1.0, 2.0, 3.0])
    led = Ledger(InMemoryStorage(), clock=lambda: next(ticks))
    e0 = led.append(actor="surface", kind="request", payload={"t": "a"})
    e1 = led.append(actor="coordinator", kind="route", payload={"to": "backend"},
                    causal_parent=e0.seq)
    e2 = led.append(actor="backend", kind="result", payload={"ok": True},
                    causal_parent=e1.seq)
    return led, (e0, e1, e2)


def test_replay_until_returns_prefix():
    led, (e0, e1, _e2) = build()
    out = led.replay(until=1)
    assert [e.seq for e in out] == [0, 1]


def test_query_filters_by_kind_and_actor():
    led, _ = build()
    assert [e.kind for e in led.query(kind="route")] == ["route"]
    assert [e.actor for e in led.query(actor="backend")] == ["backend"]


def test_causal_chain_walks_to_root():
    led, (e0, e1, e2) = build()
    chain = led.causal_chain(e2.seq)
    assert [e.seq for e in chain] == [0, 1, 2]


def test_merkle_root_is_stable_and_order_sensitive():
    assert merkle_root(["a", "b"]) == merkle_root(["a", "b"])
    assert merkle_root(["a", "b"]) != merkle_root(["b", "a"])
    assert led_checkpoint_nonempty()


def test_causal_chain_detects_cycle():
    import dataclasses
    import pytest
    led, (_e0, _e1, _e2) = build()
    storage = led._s
    # corrupt entry 1 to reference itself -> a cycle
    storage._entries[1] = dataclasses.replace(storage._entries[1], causal_parent=1)
    with pytest.raises(ValueError):
        led.causal_chain(1)


def led_checkpoint_nonempty():
    led, _ = build()
    return len(led.checkpoint()) == 64


def test_merkle_root_resists_odd_duplication_collision():
    # CVE-2012-2459 shape: [a,b,c] must NOT collide with [a,b,c,c]
    assert merkle_root(["a", "b", "c"]) != merkle_root(["a", "b", "c", "c"])
