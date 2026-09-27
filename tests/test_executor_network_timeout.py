"""ApiExecutor and ChatExecutor cap each request with a timeout.

Falsifier for the audit S5 finding: 1.14.0 called urlopen with no timeout, so a
stalled provider hung the task forever.
"""
import asyncio
import urllib.request

from forum.api_executor import ApiExecutor
from forum.chat_executor import ChatExecutor
from forum.executor import Assignment


def test_api_executor_passes_a_timeout_to_urlopen(monkeypatch):
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"content": [{"text": "ok"}]}'

    def fake_urlopen(request, *args, **kwargs):
        seen["timeout"] = kwargs.get("timeout", args[0] if args else None)
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = asyncio.run(ApiExecutor(timeout=12.5).run(Assignment("T1", "a", "hi")))
    assert result.ok is True
    assert seen["timeout"] == 12.5


def test_chat_executor_passes_a_timeout_to_urlopen(monkeypatch):
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"choices": [{"message": {"content": "ok"}}]}'

    def fake_urlopen(request, *args, **kwargs):
        seen["timeout"] = kwargs.get("timeout", args[0] if args else None)
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = asyncio.run(ChatExecutor("m", timeout=9.0).run(Assignment("T1", "a", "hi")))
    assert result.ok is True
    assert seen["timeout"] == 9.0


def test_api_executor_has_a_default_timeout():
    assert ApiExecutor()._timeout is not None
    assert ApiExecutor()._timeout > 0


def test_chat_executor_has_a_default_timeout():
    assert ChatExecutor("m")._timeout is not None
    assert ChatExecutor("m")._timeout > 0
