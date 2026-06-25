"""Forum: phased checkpoints and resumable runs (v1.9).

A long run that crashes or is stopped should not start over. Every step is witnessed
durably, so the ledger IS the resume state: re-dispatched with resume=True, the run
reuses every task already witnessed as successful and re-runs only the missing or failed
ones. No model call is spent twice, and resume reuses the verified record, it never
regenerates it.

Here the first run fails its last task; the second run resumes over the same durable
ledger, reuses the two that succeeded, and finishes. No model needed.

Run:  python examples/run_resume.py        # no install, nothing to download
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from forum.dispatch import dispatch_plan
from forum.executor import Result
from forum.ledger import Ledger
from forum.plan import Plan, Task
from forum.storage import FileStorage

PLAN = Plan(
    (
        Task("T1", "backend", "schema", ()),
        Task("T2", "backend", "endpoint", ("T1",)),
        Task("T3", "docs", "write the guide", ("T2",)),
    )
)


class FlakyThenFixed:
    """Fails T3 on the first run; succeeds everywhere on the second."""

    def __init__(self, fail_t3: bool) -> None:
        self._fail_t3 = fail_t3

    async def run(self, a):
        if a.task_id == "T3" and self._fail_t3:
            return Result("T3", a.agent, "boom: docs tool crashed", ok=False)
        return Result(a.task_id, a.agent, f"done: {a.task_id}")


def _oks(results: dict) -> dict:
    return {k: results[k].ok for k in sorted(results)}


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        led1 = Ledger(FileStorage(directory))
        run1 = asyncio.run(dispatch_plan(PLAN, led1, FlakyThenFixed(fail_t3=True)))
        print("run 1 (T3 fails)      :", _oks(run1))

        # resume over the SAME durable ledger with a working executor
        led2 = Ledger(FileStorage(directory))
        run2 = asyncio.run(dispatch_plan(PLAN, led2, FlakyThenFixed(fail_t3=False), resume=True))
        print("run 2 (resumed)       :", _oks(run2))

        reused = led2.get_payload(led2.query(kind="resume")[0].payload_hash)["reused"]
        print("reused on resume      :", reused, "(the two that already succeeded)")
        print("T3 re-run, ok now     :", run2["T3"].ok)
        print("verify(deep)          :", led2.verify(deep=True))


if __name__ == "__main__":
    main()
