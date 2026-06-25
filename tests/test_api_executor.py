import asyncio
import json

from forum.api_executor import ApiExecutor
from forum.executor import Assignment


def _fake_opener(canned_text):
    body = json.dumps({"content": [{"type": "text", "text": canned_text}]}).encode("utf-8")

    def opener(request):
        # assert we built a sane request, then return the canned bytes
        assert request.get_method() == "POST"
        assert request.full_url.endswith("/messages")
        return body

    return opener


def test_api_executor_returns_model_text():
    ex = ApiExecutor(opener=_fake_opener("the model said hi"), api_key_env="UNUSED_KEY")
    r = asyncio.run(ex.run(Assignment("T1", "worker", "say hi")))
    assert r.ok is True
    assert r.output == "the model said hi"


def test_api_executor_surfaces_an_error_as_not_ok():
    def boom(request):
        raise OSError("connection refused")

    ex = ApiExecutor(opener=boom, api_key_env="UNUSED_KEY")
    r = asyncio.run(ex.run(Assignment("T2", "worker", "x")))
    assert r.ok is False
    assert "connection refused" in r.output


def test_api_executor_handles_http_error():
    import urllib.error

    def boom(request):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    ex = ApiExecutor(opener=boom, api_key_env="UNUSED_KEY")
    r = asyncio.run(ex.run(Assignment("T3", "worker", "x")))
    assert r.ok is False
    assert "error:" in r.output


def test_api_executor_handles_malformed_response():
    def empty(request):
        return json.dumps({"content": []}).encode("utf-8")

    ex = ApiExecutor(opener=empty, api_key_env="UNUSED_KEY")
    r = asyncio.run(ex.run(Assignment("T4", "worker", "x")))
    assert r.ok is False
