import asyncio

from forum.control import Synthesizer
from forum.executor import Result


class _Canned:
    def __init__(self, output):
        self._output = output

    async def run(self, assignment):
        return Result(assignment.task_id, assignment.agent, self._output)


def test_synthesizer_returns_an_answer():
    results = {
        "T1": Result("T1", "backend", "built the api"),
        "T2": Result("T2", "docs", "wrote the docs"),
    }
    answer = asyncio.run(Synthesizer().synthesize("ship an api with docs", results, _Canned("done: api and docs shipped")))
    assert answer == "done: api and docs shipped"
