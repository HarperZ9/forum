import asyncio

import pytest

from forum.control import Classification, Classifier
from forum.executor import Result
from forum.roster import loads

ROSTER = loads('[[agent]]\nname="backend"\ncategory="engineering"\ndomain="apis"\nkeywords=["api"]\nmodel_tier="capable"\nexecutor="echo"\n')


class _Canned:
    def __init__(self, output):
        self._output = output

    async def run(self, assignment):
        return Result(assignment.task_id, assignment.agent, self._output)


def test_classifier_picks_an_agent():
    ex = _Canned('{"agent": "backend", "confidence": 0.8, "reason": "it is an api task"}')
    c = asyncio.run(Classifier().classify("build the api", ROSTER, ex))
    assert isinstance(c, Classification)
    assert c.agent == "backend"
    assert c.confidence == 0.8


def test_classifier_rejects_unknown_agent():
    ex = _Canned('{"agent": "ghost", "confidence": 1.0}')
    with pytest.raises(ValueError, match="ghost"):
        asyncio.run(Classifier().classify("x", ROSTER, ex))
