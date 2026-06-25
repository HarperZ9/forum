import asyncio
import json

from forum.chat_executor import ChatExecutor
from forum.executor import Assignment


def _opener_returning(text):
    body = json.dumps({"choices": [{"message": {"role": "assistant", "content": text}}]}).encode("utf-8")
    captured = {}

    def opener(request):
        captured["auth"] = request.get_header("Authorization")
        captured["url"] = request.full_url
        return body

    return opener, captured


def test_chat_executor_returns_model_text():
    opener, captured = _opener_returning("local model says hi")
    ex = ChatExecutor("llama3", base_url="http://localhost:11434/v1/chat/completions", opener=opener)
    r = asyncio.run(ex.run(Assignment("T1", "worker", "hi")))
    assert r.ok is True
    assert r.output == "local model says hi"
    assert captured["auth"] is None  # a local server needs no account or key


def test_chat_executor_sends_bearer_when_key_is_set(monkeypatch):
    monkeypatch.setenv("MYPROVIDER_KEY", "sk-test")
    opener, captured = _opener_returning("hi")
    ex = ChatExecutor(
        "gpt-x", base_url="https://api.example.com/v1/chat/completions",
        api_key_env="MYPROVIDER_KEY", opener=opener,
    )
    asyncio.run(ex.run(Assignment("T2", "worker", "x")))
    assert captured["auth"] == "Bearer sk-test"


def test_chat_executor_surfaces_a_network_error():
    def boom(request):
        raise OSError("connection refused")

    ex = ChatExecutor("m", opener=boom)
    r = asyncio.run(ex.run(Assignment("T3", "worker", "x")))
    assert r.ok is False
    assert "connection refused" in r.output


def test_chat_executor_handles_malformed_response():
    def odd(request):
        return json.dumps({"error": "nope"}).encode("utf-8")

    ex = ChatExecutor("m", opener=odd)
    r = asyncio.run(ex.run(Assignment("T4", "worker", "x")))
    assert r.ok is False
    assert "unexpected chat response shape" in r.output
