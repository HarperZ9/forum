import dataclasses

import pytest

from forum.ledger import InMemoryStorage, Ledger
from forum.sqlite_storage import SqliteStorage
from forum.storage import StorageCorruption


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


def _db(tmp_path, **kw):
    return SqliteStorage(str(tmp_path / "ledger.db"), **kw)


def test_sqlite_round_trips_within_a_session(tmp_path):
    led = _ledger(_db(tmp_path))
    _populate(led)
    assert [e.seq for e in led.replay()] == [0, 1, 2]
    assert led.verify(deep=True) is True
    assert led._s.head().seq == 2
    assert led._s.get(1).kind == "plan"
    assert led._s.count() == 3


def test_sqlite_survives_restart(tmp_path):
    store = _db(tmp_path)
    led = _ledger(store)
    _populate(led)
    checkpoint_before = led.checkpoint()
    store.sync()
    store.close()

    reopened = Ledger(_db(tmp_path))
    assert [e.seq for e in reopened.replay()] == [0, 1, 2]
    assert reopened.verify(deep=True) is True
    assert reopened.checkpoint() == checkpoint_before
    head = reopened._s.get(0)
    assert reopened._s.get_payload(head.payload_hash) == {"text": "ship it"}


def test_sqlite_matches_in_memory_byte_for_byte(tmp_path):
    mem = _ledger(InMemoryStorage())
    sql = _ledger(_db(tmp_path))
    _populate(mem)
    _populate(sql)
    assert [dataclasses.astuple(e) for e in mem.replay()] == [
        dataclasses.astuple(e) for e in sql.replay()
    ]
    assert mem.checkpoint() == sql.checkpoint()


def test_sqlite_get_out_of_range_raises_keyerror(tmp_path):
    led = _ledger(_db(tmp_path))
    _populate(led)
    with pytest.raises(KeyError):
        led._s.get(99)
    with pytest.raises(KeyError):
        led._s.get(-1)


def test_sqlite_empty_db_is_a_valid_empty_ledger(tmp_path):
    led = _ledger(_db(tmp_path))
    assert led.replay() == []
    assert led.verify(deep=True) is True
    assert led._s.head() is None
    assert led._s.count() == 0
    assert led.checkpoint() == "0" * 64


def test_sqlite_get_payload_missing_raises_keyerror(tmp_path):
    led = _ledger(_db(tmp_path))
    _populate(led)
    with pytest.raises(KeyError):
        led._s.get_payload("deadbeef" * 8)


def test_sqlite_put_payload_first_write_wins(tmp_path):
    store = _db(tmp_path)
    store.put_payload("h1", {"v": 1})
    store.put_payload("h1", {"v": 2})  # ignored: first body wins (setdefault)
    assert store.get_payload("h1") == {"v": 1}


def test_sqlite_batched_durability(tmp_path):
    # fsync_each=False accumulates in one transaction; visible in-session, and
    # durable only after sync() -> survives a reopen.
    store = _db(tmp_path, fsync_each=False)
    led = _ledger(store)
    _populate(led)
    assert led.verify(deep=True) is True  # visible before sync within the session
    cp = led.checkpoint()
    store.sync()
    store.close()
    reopened = Ledger(_db(tmp_path, fsync_each=False))
    assert reopened.checkpoint() == cp
    assert reopened.verify(deep=True) is True


def test_sqlite_point_reads_match_all_at_scale(tmp_path):
    # The RAM-free path: head/get/count are indexed point reads. Assert they
    # agree with a full all() scan over a larger ledger.
    store = _db(tmp_path, fsync_each=False)
    ticks = iter(float(t) for t in range(1, 2001))
    led = Ledger(store, clock=lambda: next(ticks))
    for i in range(500):
        led.append(actor="a", kind="k", payload={"i": i})
    store.sync()
    entries = store.all()
    assert store.count() == len(entries) == 500
    assert store.head().seq == 499
    assert store.get(250).seq == 250
    assert store.get(250).entry_hash == entries[250].entry_hash
    assert led.verify(deep=True) is True


def test_sqlite_non_database_file_raises_corruption(tmp_path):
    bad = tmp_path / "not.db"
    bad.write_bytes(b"this is not a sqlite database, it is plain text\n" * 4)
    with pytest.raises(StorageCorruption):
        SqliteStorage(str(bad))


def test_open_ledger_routes_db_path_to_sqlite(tmp_path):
    from forum.cli import _open_ledger
    from forum.storage import FileStorage

    led_db = _open_ledger(str(tmp_path / "l.db"))
    assert isinstance(led_db._s, SqliteStorage)
    led_dir = _open_ledger(str(tmp_path / "ldir"))
    assert isinstance(led_dir._s, FileStorage)
    # the sqlite-routed ledger round-trips
    led_db.append(actor="a", kind="k", payload={"x": 1})
    assert led_db.verify(deep=True) is True


def test_sqlite_creates_missing_parent_directory(tmp_path):
    # a .db path under a not-yet-existing directory is created, not an error
    store = SqliteStorage(str(tmp_path / "nested" / "deep" / "ledger.db"))
    store.put_payload("h", {"ok": True})
    assert store.get_payload("h") == {"ok": True}
    store.close()
