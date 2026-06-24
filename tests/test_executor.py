import asyncio

from forum.executor import Assignment, EchoExecutor, Result


def test_echo_executor_is_deterministic():
    a = Assignment("T1", "backend", "build the schema")
    r = asyncio.run(EchoExecutor().run(a))
    assert isinstance(r, Result)
    assert (r.task_id, r.agent, r.output, r.ok) == ("T1", "backend", "done: build the schema", True)
