from __future__ import annotations

import asyncio
import json
import os
import urllib.request

from forum.executor import Assignment, Result


class ApiExecutor:
    """Drive a model via the Anthropic Messages API over stdlib ``urllib``.

    Network IO lives here, at the edge. ``opener`` is a callable
    ``(urllib.request.Request) -> bytes`` that performs the request; it is
    injected in tests so no real network is hit. The default opens the request
    with ``urllib.request.urlopen``. The blocking call runs off the event loop
    via ``asyncio.to_thread``.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        *,
        api_key_env: str = "ANTHROPIC_API_KEY",
        base_url: str = "https://api.anthropic.com/v1/messages",
        max_tokens: int = 1024,
        opener=None,
    ) -> None:
        self._model = model
        self._api_key_env = api_key_env
        self._base_url = base_url
        self._max_tokens = max_tokens
        self._opener = opener or _default_opener

    @property
    def model_id(self) -> str:
        return self._model

    async def run(self, assignment: Assignment) -> Result:
        request = self._build_request(assignment.instruction)
        try:
            raw = await asyncio.to_thread(self._opener, request)
        except Exception as exc:
            return Result(assignment.task_id, assignment.agent, f"error: {exc}", ok=False)
        text = _extract_text(raw)
        if text is None:
            preview = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
            return Result(
                assignment.task_id, assignment.agent,
                f"error: unexpected API response shape: {preview[:200]!r}", ok=False,
            )
        return Result(assignment.task_id, assignment.agent, text, ok=True)

    def _build_request(self, instruction: str) -> urllib.request.Request:
        body = json.dumps(
            {
                "model": self._model,
                "max_tokens": self._max_tokens,
                "messages": [{"role": "user", "content": instruction}],
            }
        ).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": os.environ.get(self._api_key_env, ""),
        }
        return urllib.request.Request(self._base_url, data=body, headers=headers, method="POST")


def _extract_text(raw) -> str | None:
    """Pull the assistant text from an Anthropic Messages response, or None if
    the payload is not the expected {"content": [{"text": ...}]} shape."""
    try:
        data = json.loads(raw)
        content = data["content"]
        if isinstance(content, list) and content and isinstance(content[0], dict) and "text" in content[0]:
            return content[0]["text"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    return None


def _default_opener(request: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(request) as response:
        return response.read()
