from __future__ import annotations

import asyncio
import json
import os
import urllib.request

from forum.executor import Assignment, Result


class ChatExecutor:
    """Drive any OpenAI-compatible chat-completions endpoint over stdlib urllib.

    This is the model-agnostic path. It speaks the widely-implemented
    ``/v1/chat/completions`` protocol, so it works with local servers that need
    no account (Ollama, LM Studio, llama.cpp, vLLM) and with OpenAI-compatible
    cloud providers alike. Point ``base_url`` at your server and name the model.
    An API key is optional (local servers usually need none); when ``api_key_env``
    names a non-empty environment variable, its value is sent as a Bearer token.

    Network IO lives here, at the edge. ``opener`` is a callable
    ``(urllib.request.Request) -> bytes`` injected in tests so no real network is
    hit; the blocking call runs off the event loop via ``asyncio.to_thread``.
    """

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://localhost:11434/v1/chat/completions",
        api_key_env: str | None = None,
        max_tokens: int = 1024,
        opener=None,
    ) -> None:
        self._model = model
        self._base_url = base_url
        self._api_key_env = api_key_env
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
                f"error: unexpected chat response shape: {preview[:200]!r}", ok=False,
            )
        return Result(assignment.task_id, assignment.agent, text, ok=True)

    def _build_request(self, instruction: str) -> urllib.request.Request:
        body = json.dumps(
            {
                "model": self._model,
                # max_tokens is accepted by OpenAI (back-compat) and by every local
                # server we target; newer OpenAI models also accept max_completion_tokens.
                "max_tokens": self._max_tokens,
                "messages": [{"role": "user", "content": instruction}],
            }
        ).encode("utf-8")
        headers = {"content-type": "application/json"}
        if self._api_key_env:
            key = os.environ.get(self._api_key_env, "")
            if key:
                headers["authorization"] = f"Bearer {key}"
        return urllib.request.Request(self._base_url, data=body, headers=headers, method="POST")


def _extract_text(raw) -> str | None:
    """Pull the assistant text from an OpenAI-compatible chat-completions reply,
    or None if the payload is not the expected choices[0].message.content shape."""
    try:
        data = json.loads(raw)
        choices = data["choices"]
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    # some OpenAI-compatible gateways return content as a list of
                    # {type, text} parts; join the text parts
                    joined = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                    if joined:
                        return joined
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    return None


def _default_opener(request: urllib.request.Request) -> bytes:
    with urllib.request.urlopen(request) as response:
        return response.read()
