import asyncio
import sys

from forum.executor import Assignment, SubprocessExecutor


def test_subprocess_executor_runs_a_command():
    # echo the instruction back via a tiny python program
    ex = SubprocessExecutor([sys.executable, "-c", "import sys; print('ran:', sys.argv[1])"])
    r = asyncio.run(ex.run(Assignment("T1", "worker", "hello")))
    assert r.ok is True
    assert r.output == "ran: hello"


def test_subprocess_executor_reports_failure():
    ex = SubprocessExecutor([sys.executable, "-c", "import sys; sys.exit(3)"])
    r = asyncio.run(ex.run(Assignment("T2", "worker", "x")))
    assert r.ok is False
