import asyncio

from forum.control import Validator, Verdict
from forum.executor import Result


class _Canned:
    def __init__(self, output):
        self._output = output

    async def run(self, assignment):
        return Result(assignment.task_id, assignment.agent, self._output)


def test_validator_returns_a_verdict():
    ex = _Canned('{"ok": true, "score": 0.95, "reason": "meets the instruction"}')
    v = asyncio.run(Validator().validate("build the api", "the api", ex))
    assert isinstance(v, Verdict)
    assert v.ok is True
    assert v.score == 0.95


def test_validator_can_fail():
    ex = _Canned('{"ok": false, "score": 0.1, "reason": "off topic"}')
    v = asyncio.run(Validator().validate("build the api", "a poem", ex))
    assert v.ok is False
