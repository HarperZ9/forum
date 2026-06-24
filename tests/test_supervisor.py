import asyncio

import pytest

from forum.supervisor import Supervisor


def test_supervisor_restarts_then_succeeds():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("boom")
        return "ok"

    sup = Supervisor("s", max_restarts=3)
    assert asyncio.run(sup.run(flaky)) == "ok"
    assert calls["n"] == 3
    assert sup.restarts == 2


def test_supervisor_gives_up_after_max():
    async def always():
        raise RuntimeError("nope")

    sup = Supervisor("s", max_restarts=2)
    with pytest.raises(RuntimeError):
        asyncio.run(sup.run(always))
    assert sup.restarts == 2
