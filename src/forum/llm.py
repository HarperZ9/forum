from __future__ import annotations

import json

from forum.executor import Assignment, Executor


async def ask_json(executor: Executor, agent: str, prompt: str) -> dict:
    """Run the executor on a prompt and parse a JSON object from its reply.

    Tolerant: extracts the span from the first ``{`` to the last ``}``, so a
    model that wraps JSON in prose or code fences still parses. Raises
    ``ValueError`` when no JSON object is present.
    """
    result = await executor.run(Assignment("control", agent, prompt))
    text = result.output
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON object in output: {text[:200]!r}")
    snippet = text[start : end + 1]
    try:
        return json.loads(snippet)
    except json.JSONDecodeError as exc:
        raise ValueError(f"could not parse JSON from output: {exc}") from exc
