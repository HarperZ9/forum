import asyncio

from forum.actor import Actor


class Collector(Actor):
    def __init__(self):
        super().__init__("collector")
        self.seen = []

    async def on_message(self, message):
        self.seen.append(message)


def test_actor_processes_in_order_then_stops():
    async def scenario():
        a = Collector().start()
        await a.send("x")
        await a.send("y")
        await a.stop()
        return a.seen

    assert asyncio.run(scenario()) == ["x", "y"]


class Boom(Actor):
    def __init__(self):
        super().__init__("boom")

    async def on_message(self, message):
        raise ValueError("bad message")


def test_actor_records_on_message_error_and_stops():
    async def scenario():
        a = Boom().start()
        await a.send("x")
        await a.stop()
        return a.error

    err = asyncio.run(scenario())
    assert isinstance(err, ValueError)


def test_stop_before_start_is_safe():
    async def scenario():
        a = Collector()
        await a.stop()  # no task running; must be a clean no-op
        return "ok"

    assert asyncio.run(scenario()) == "ok"
