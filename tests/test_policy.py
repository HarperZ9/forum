from forum.policy import Policy
from forum.roster import AgentSpec


def spec(category):
    return AgentSpec("x", category, "d", ("k",), "cheap", "claude-code")


def test_permits_only_allowed_categories():
    pol = Policy(allowed_categories=frozenset({"engineering", "research"}))
    assert pol.permits(spec("engineering")) is True
    assert pol.permits(spec("graphics")) is False


def test_cap_wave_splits_by_max_parallel():
    pol = Policy(allowed_categories=frozenset({"engineering"}), max_parallel=2)
    assert pol.cap_wave(["A", "B", "C", "D", "E"]) == [["A", "B"], ["C", "D"], ["E"]]
