import pytest


@pytest.fixture(autouse=True)
def _clarify_builtin_engine(monkeypatch):
    """Pin clarify to the built-in rules so results do not depend on whether
    Articulate happens to be installed. Tests of the handoff override this."""
    monkeypatch.setenv("FORUM_CLARIFY_ENGINE", "forum-builtin")
    monkeypatch.delenv("FORUM_ARTICULATE_CLI", raising=False)
