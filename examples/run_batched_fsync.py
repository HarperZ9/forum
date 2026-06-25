"""Forum: opt-in batched fsync (v1.8).

The durable ledger fsyncs every append by default, the strongest guarantee. When a
high-throughput run makes that per-append fsync the bottleneck, fsync_each=False defers
it: appends are flushed to the OS (so they survive a process crash) but synced to disk
only when you call ledger.sync(). The tradeoff is plain: a crash before sync() can lose
the un-fsynced tail; whatever survived still verifies and replays exactly.

Run:  python examples/run_batched_fsync.py        # no install, nothing to download
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.ledger import Ledger
from forum.storage import FileStorage


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        led = Ledger(FileStorage(directory, fsync_each=False))  # batched durability
        for i in range(5):
            led.append(actor="client", kind="request", payload={"i": i})
        print("appended 5 entries in batched mode (no per-append fsync)")

        led.sync()  # fsync the logs at a point of our choosing
        print("called ledger.sync() -> the logs are fsynced to disk")

        reopened = Ledger(FileStorage(directory))  # recover from disk
        print("reopened entries :", reopened.count())
        print("verify(deep)     :", reopened.verify(deep=True))
        print("checkpoint match :", reopened.checkpoint() == led.checkpoint())


if __name__ == "__main__":
    main()
