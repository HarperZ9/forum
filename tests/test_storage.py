import dataclasses

import pytest

from forum.ledger import InMemoryStorage, Ledger
from forum.storage import FileStorage


def _ledger(storage, n_ticks=50):
    ticks = iter(float(t) for t in range(1, n_ticks + 1))
    return Ledger(storage, clock=lambda: next(ticks))


def _populate(led):
    e0 = led.append(actor="client", kind="request", payload={"text": "ship it"})
    e1 = led.append(
        actor="coordinator", kind="plan", payload={"tasks": ["T1"]}, causal_parent=e0.seq
    )
    e2 = led.append(
        actor="worker", kind="result", payload={"id": "T1", "output": "done"},
        causal_parent=e1.seq,
    )
    return e0, e1, e2


def test_filestorage_round_trips_within_a_session(tmp_path):
    led = _ledger(FileStorage(str(tmp_path)))
    _populate(led)
    assert [e.seq for e in led.replay()] == [0, 1, 2]
    assert led.verify(deep=True) is True
    assert led._s.head().seq == 2
    assert led._s.get(1).kind == "plan"


def test_filestorage_survives_restart(tmp_path):
    led = _ledger(FileStorage(str(tmp_path)))
    _populate(led)
    checkpoint_before = led.checkpoint()

    reopened = Ledger(FileStorage(str(tmp_path)))
    assert [e.seq for e in reopened.replay()] == [0, 1, 2]
    assert reopened.verify(deep=True) is True
    assert reopened.checkpoint() == checkpoint_before
    head = reopened._s.get(0)
    assert reopened._s.get_payload(head.payload_hash) == {"text": "ship it"}


def test_filestorage_matches_in_memory_byte_for_byte(tmp_path):
    mem = _ledger(InMemoryStorage())
    fil = _ledger(FileStorage(str(tmp_path)))
    _populate(mem)
    _populate(fil)
    assert [dataclasses.astuple(e) for e in mem.replay()] == [
        dataclasses.astuple(e) for e in fil.replay()
    ]
    assert mem.checkpoint() == fil.checkpoint()


def test_filestorage_get_out_of_range_raises_keyerror(tmp_path):
    led = _ledger(FileStorage(str(tmp_path)))
    _populate(led)
    with pytest.raises(KeyError):
        led._s.get(99)


def test_filestorage_empty_directory_is_a_valid_empty_ledger(tmp_path):
    led = _ledger(FileStorage(str(tmp_path)))
    assert led.replay() == []
    assert led._s.head() is None
    assert led.verify() is True
    assert led.checkpoint() == "0" * 64
