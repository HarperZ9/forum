from __future__ import annotations

import asyncio
from typing import Any

_STOP = object()


class Actor:
    """A minimal mailbox actor: an async receive loop over a queue."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.inbox: asyncio.Queue[Any] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self.error: BaseException | None = None

    async def on_message(self, message: Any) -> None:
        raise NotImplementedError

    async def _loop(self) -> None:
        while True:
            message = await self.inbox.get()
            if message is _STOP:
                break
            try:
                await self.on_message(message)
            except Exception as exc:  # let-it-crash, but observable
                self.error = exc
                break

    def start(self) -> "Actor":
        self._task = asyncio.create_task(self._loop())
        return self

    async def send(self, message: Any) -> None:
        await self.inbox.put(message)

    async def stop(self) -> None:
        if self._task is None:
            return
        await self.inbox.put(_STOP)
        await self._task
