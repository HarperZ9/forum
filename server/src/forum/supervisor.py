from __future__ import annotations

from typing import Any, Awaitable, Callable

CoroFactory = Callable[[], Awaitable[Any]]


class Supervisor:
    """Run a coroutine factory under a let-it-crash restart policy.

    On exception, re-invoke the factory up to ``max_restarts`` times before
    giving up and re-raising the last exception.
    """

    def __init__(self, name: str, max_restarts: int = 3) -> None:
        self.name = name
        self.max_restarts = max_restarts
        self.restarts = 0

    async def run(self, factory: CoroFactory) -> Any:
        attempt = 0
        while True:
            try:
                return await factory()
            except Exception:
                if attempt >= self.max_restarts:
                    raise
                attempt += 1
                self.restarts += 1
