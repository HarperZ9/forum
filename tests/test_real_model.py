import asyncio
import os

import pytest

from forum.api_executor import ApiExecutor
from forum.engine import Orchestrator
from forum.ledger import InMemoryStorage, Ledger
from forum.policy import Policy
from forum.roster import load_default

# The real-model proof: this makes live Anthropic API calls and costs money, so
# it runs only when explicitly enabled. It is skipped in CI and in normal runs.
_ENABLED = os.environ.get("FORUM_RUN_REAL") == "1" and bool(os.environ.get("ANTHROPIC_API_KEY"))

pytestmark = pytest.mark.skipif(
    not _ENABLED,
    reason="set FORUM_RUN_REAL=1 and ANTHROPIC_API_KEY to run the real-model proof",
)

ALL_CATEGORIES = frozenset({"engineering", "graphics", "support", "research"})


def test_real_model_submit_is_witnessed_and_verifiable():
    ledger = Ledger(InMemoryStorage())
    orch = Orchestrator(
        load_default(),
        ledger,
        ApiExecutor(),  # default model; reads ANTHROPIC_API_KEY
        Policy(allowed_categories=ALL_CATEGORIES, max_parallel=2),
    )
    answer = asyncio.run(
        orch.submit("Write a one-sentence description of a REST API for a todo list.")
    )
    assert isinstance(answer, str) and answer.strip()
    assert ledger.query(kind="request")
    assert ledger.query(kind="result")
    assert ledger.verify(deep=True) is True       # the whole live run stays tamper-evident
    assert ledger.checkpoint() != "0" * 64


def test_real_model_assign_routes_a_single_task():
    ledger = Ledger(InMemoryStorage())
    orch = Orchestrator(
        load_default(), ledger, ApiExecutor(),
        Policy(allowed_categories=ALL_CATEGORIES, max_parallel=2),
    )
    result = asyncio.run(orch.submit_one("design a database schema for a blog"))
    assert result.output.strip()
    assert ledger.verify(deep=True) is True
