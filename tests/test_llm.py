import asyncio

import pytest

from forum.executor import Result
from forum.llm import ask_json


class _CannedExecutor:
    def __init__(self, output):
        self._output = output

    async def run(self, assignment):
        return Result(assignment.task_id, assignment.agent, self._output)


def test_ask_json_extracts_object_from_prose():
    ex = _CannedExecutor('Sure! Here you go:\n{"agent": "backend", "confidence": 0.9}\nHope that helps.')
    data = asyncio.run(ask_json(ex, "classifier", "prompt"))
    assert data == {"agent": "backend", "confidence": 0.9}


def test_ask_json_raises_without_json():
    ex = _CannedExecutor("no json here")
    with pytest.raises(ValueError):
        asyncio.run(ask_json(ex, "classifier", "prompt"))
