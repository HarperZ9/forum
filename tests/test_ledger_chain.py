from forum.ledger import GENESIS, InMemoryStorage, Ledger


def make_ledger():
    ticks = iter([1.0, 2.0, 3.0, 4.0])
    return Ledger(InMemoryStorage(), clock=lambda: next(ticks))


def test_append_links_chain_and_increments_seq():
    led = make_ledger()
    e0 = led.append(actor="surface", kind="request", payload={"t": "a"})
    e1 = led.append(actor="coordinator", kind="route", payload={"to": "backend"})
    assert e0.seq == 0 and e1.seq == 1
    assert e0.prev_hash == GENESIS
    assert e1.prev_hash == e0.entry_hash


def test_verify_passes_on_clean_chain():
    led = make_ledger()
    led.append(actor="surface", kind="request", payload={"t": "a"})
    led.append(actor="coordinator", kind="route", payload={"to": "backend"})
    assert led.verify() is True


def test_verify_detects_tamper():
    storage = InMemoryStorage()
    ticks = iter([1.0, 2.0])
    led = Ledger(storage, clock=lambda: next(ticks))
    led.append(actor="surface", kind="request", payload={"t": "a"})
    led.append(actor="coordinator", kind="route", payload={"to": "backend"})
    # Mutate a stored entry's actor without recomputing its hash.
    import dataclasses
    storage._entries[0] = dataclasses.replace(storage._entries[0], actor="evil")
    assert led.verify() is False


def test_get_raises_on_missing_seq():
    import pytest
    led = make_ledger()
    led.append(actor="surface", kind="request", payload={"t": "a"})
    storage = led._s
    with pytest.raises(KeyError):
        storage.get(5)


def test_verify_payloads_detects_body_swap():
    led = make_ledger()
    led.append(actor="surface", kind="request", payload={"t": "a"})
    storage = led._s
    entry = storage.get(0)
    storage._payloads[entry.payload_hash] = {"t": "EVIL"}  # tamper body, keep key
    assert led.verify() is True            # chain alone is still valid
    assert led.verify_payloads() is False  # body tamper caught
    assert led.verify(deep=True) is False   # deep verify catches it


def test_verify_payloads_tolerates_redacted():
    led = make_ledger()
    led.append(actor="surface", kind="request", payload={"t": "a"})
    storage = led._s
    entry = storage.get(0)
    del storage._payloads[entry.payload_hash]  # hash-only / redacted
    assert led.verify_payloads() is True       # absence is allowed
