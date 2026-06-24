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
