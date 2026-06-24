from forum.roster import loads
from forum.routing import LexicalRouter, RouteResult

ROSTER = loads(
    """
[[agent]]
name="backend"
category="engineering"
domain="backend"
keywords=["backend","api","database","schema"]
model_tier="capable"
executor="claude-code"

[[agent]]
name="frontend"
category="engineering"
domain="frontend"
keywords=["frontend","react","css","animation"]
model_tier="capable"
executor="claude-code"
"""
)


def test_confident_single_route():
    r = LexicalRouter().score("design the database schema and api", ROSTER)
    assert isinstance(r, RouteResult)
    assert r.decided == "backend"
    assert r.needs_escalation is False
    assert r.candidates[0].agent == "backend"
    assert r.confidence == r.candidates[0].score  # confidence == top score when decided


def test_zero_match_escalates():
    r = LexicalRouter().score("compose a symphony in D minor", ROSTER)
    assert r.decided is None
    assert r.needs_escalation is True


def test_ambiguous_tie_escalates():
    # one keyword hit each -> tie below margin -> escalate
    r = LexicalRouter().score("api and react", ROSTER)
    assert r.decided is None
    assert r.needs_escalation is True
