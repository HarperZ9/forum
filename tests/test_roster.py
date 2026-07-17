import pytest

from forum.roster import AgentSpec, loads

SAMPLE = """
[[agent]]
name = "backend"
category = "engineering"
domain = "Full-stack backend & applications"
keywords = ["backend", "api", "database"]
model_tier = "capable"
executor = "claude-code"
max_turns = 15

[[agent]]
name = "deep-research"
category = "research"
domain = "Academic & technical deep research"
keywords = ["paper", "rfc", "algorithm"]
model_tier = "cheap"
executor = "claude-code"
"""


def test_loads_parses_agents():
    roster = loads(SAMPLE)
    assert len(roster.agents) == 2
    backend = roster.by_name("backend")
    assert isinstance(backend, AgentSpec)
    assert backend.category == "engineering"
    assert backend.keywords == ("backend", "api", "database")
    assert backend.max_turns == 15
    assert roster.by_name("deep-research").max_turns == 10  # default


def test_invalid_tier_rejected():
    bad = '[[agent]]\nname="x"\ncategory="c"\ndomain="d"\nkeywords=["k"]\nmodel_tier="genius"\nexecutor="claude-code"\n'
    with pytest.raises(ValueError, match="model_tier"):
        loads(bad)


def test_empty_keywords_rejected():
    bad = '[[agent]]\nname="x"\ncategory="c"\ndomain="d"\nkeywords=[]\nmodel_tier="cheap"\nexecutor="claude-code"\n'
    with pytest.raises(ValueError, match="keywords"):
        loads(bad)


def test_keywords_must_be_a_list():
    bad = '[[agent]]\nname="x"\ncategory="c"\ndomain="d"\nkeywords="backend"\nmodel_tier="cheap"\nexecutor="claude-code"\n'
    with pytest.raises(ValueError, match="keywords"):
        loads(bad)


def test_missing_required_field_rejected():
    bad = '[[agent]]\nname="x"\ncategory="c"\ndomain="d"\nkeywords=["k"]\nmodel_tier="cheap"\n'
    with pytest.raises(ValueError, match="executor"):
        loads(bad)


def test_duplicate_agent_names_are_rejected():
    # two rows named the same agent double-count one actor and let it suppress
    # or impersonate; a roster's names must be unique
    dup = SAMPLE + """
[[agent]]
name = "backend"
category = "engineering"
domain = "a second backend, same name"
keywords = ["server"]
model_tier = "cheap"
executor = "claude-code"
"""
    with pytest.raises(ValueError, match="duplicate agent name"):
        loads(dup)
