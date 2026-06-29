from forum.roster import Roster, load_default
from forum.routing import LexicalRouter

EXPECTED_CATEGORIES = {"engineering", "graphics", "support", "research"}
EXPECTED_DEFAULT_ROSTER_SIZE = 28


def test_load_default_returns_the_full_roster():
    roster = load_default()
    assert isinstance(roster, Roster)
    assert len(roster.agents) == EXPECTED_DEFAULT_ROSTER_SIZE
    assert roster.by_name("project-telos") is not None
    assert roster.by_name("model-foundry") is not None
    assert roster.by_name("function-routing") is not None
    assert roster.by_name("prose-humanization") is not None


def test_default_roster_names_are_unique():
    roster = load_default()
    names = [a.name for a in roster.agents]
    assert len(set(names)) == len(names)


def test_default_roster_categories_match_the_design():
    roster = load_default()
    assert {a.category for a in roster.agents} == EXPECTED_CATEGORIES


def test_default_roster_keywords_are_nonempty_single_tokens():
    roster = load_default()
    for a in roster.agents:
        assert a.keywords, f"{a.name} has no keywords"
        for kw in a.keywords:
            assert kw == kw.lower(), f"{a.name} keyword {kw!r} is not lowercase"
            assert kw.isalnum(), f"{a.name} keyword {kw!r} is not a single alnum token"


def test_every_default_lane_routes_to_itself():
    # Feeding a lane's own keywords must decide that lane: this proves the
    # keyword sets are distinct and decisive enough for the router (no lane is
    # shadowed by another), which is what makes the shipped roster usable.
    roster = load_default()
    router = LexicalRouter()
    for spec in roster.agents:
        request = " ".join(spec.keywords)
        result = router.score(request, roster)
        assert result.decided == spec.name, (
            f"{spec.name!r} routed to {result.decided!r} (confidence {result.confidence:.2f})"
        )


def test_model_foundry_requests_route_without_escalation():
    roster = load_default()
    result = LexicalRouter().score(
        "Build Telos into a bounded model foundry with a self improving daemon, "
        "large context second brain, eval gated promotion, MCP native integration, "
        "and receipt chained agent workflow.",
        roster,
    )
    assert result.decided == "model-foundry"
    assert result.needs_escalation is False
    assert result.confidence >= 0.8
    assert result.candidates[0].agent == "model-foundry"


def test_broad_project_telos_operator_requests_keep_secondary_lanes_without_escalation():
    roster = load_default()
    result = LexicalRouter().score(
        "Continue improving the five Project Telos flagship tools as protocol agnostic "
        "enterprise AI workflow tools, with MCP CLI compatibility, accessibility, "
        "performance, current rendering research, and second brain integration.",
        roster,
    )
    assert result.decided == "project-telos"
    assert result.needs_escalation is False
    assert result.confidence >= 0.5
    assert result.candidates[0].agent == "project-telos"
    assert {"render-pipeline", "deep-research", "function-routing"} <= {
        candidate.agent for candidate in result.candidates[:8]
    }


def test_no_persona_names_in_default_roster():
    # Clean-room constraint: plain capability slugs, never the ecosystem
    # persona names.
    roster = load_default()
    personas = {
        "anvil", "bastion", "conduit", "filament", "meridian", "parallax",
        "prism", "keystone", "herald", "loom", "sentinel", "scholar", "scout",
        "digest", "chronicle", "tutor", "spectrum", "specter",
    }
    assert not ({a.name for a in roster.agents} & personas)
