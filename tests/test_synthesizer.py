import asyncio

from forum.control import Synthesizer
from forum.executor import Result


class _Canned:
    def __init__(self, output):
        self._output = output
        self.assignments = []

    async def run(self, assignment):
        self.assignments.append(assignment)
        return Result(assignment.task_id, assignment.agent, self._output)


def test_synthesizer_returns_an_answer():
    results = {
        "T1": Result("T1", "backend", "built the api"),
        "T2": Result("T2", "docs", "wrote the docs"),
    }
    answer = asyncio.run(Synthesizer().synthesize("ship an api with docs", results, _Canned("done: api and docs shipped")))
    assert answer == "done: api and docs shipped"


def test_synthesizer_includes_delivery_contract_when_provided():
    executor = _Canned("done")
    results = {"T1": Result("T1", "backend", "built the api")}
    asyncio.run(
        Synthesizer().synthesize(
            "ship an api",
            results,
            executor,
            delivery_contract="Answer as an implementation architect.",
        )
    )
    prompt = executor.assignments[0].instruction
    assert "Delivery contract:" in prompt
    assert "Answer as an implementation architect." in prompt
    assert prompt.index("Delivery contract:") < prompt.index("Write the final answer.")


def test_synthesizer_omits_delivery_contract_by_default():
    executor = _Canned("done")
    results = {"T1": Result("T1", "backend", "built the api")}
    asyncio.run(Synthesizer().synthesize("ship an api", results, executor))
    assert "Delivery contract:" not in executor.assignments[0].instruction
