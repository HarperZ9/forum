import pytest

from forum.ledger import InMemoryStorage, Ledger


def _ledger():
    ticks = iter(float(t) for t in range(1, 10))
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def test_get_returns_the_entry_at_seq():
    led = _ledger()
    led.append(actor="client", kind="request", payload={"t": "a"})
    e1 = led.append(actor="worker", kind="result", payload={"t": "b"})
    assert led.get(1) is e1
    assert led.get(0).kind == "request"


def test_get_raises_keyerror_when_absent():
    led = _ledger()
    led.append(actor="client", kind="request", payload={"t": "a"})
    with pytest.raises(KeyError):
        led.get(5)


def test_count_tracks_entries():
    led = _ledger()
    assert led.count() == 0
    led.append(actor="client", kind="request", payload={"t": "a"})
    led.append(actor="worker", kind="result", payload={"t": "b"})
    assert led.count() == 2
