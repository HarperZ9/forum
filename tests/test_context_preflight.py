from forum.context_budget import ContextBudget


def test_context_preflight_reports_request_size_without_context():
    from forum.context_preflight import build_context_preflight

    payload = build_context_preflight("build api")

    assert payload == {
        "schema": "forum.context-preflight/v1",
        "ready": True,
        "request": {"bytes": 9, "tokens": 3},
        "context": {
            "source": "none",
            "action": "none",
            "reason": "no_context",
            "original_tokens": 0,
            "admitted_tokens": 0,
            "tokens_saved": 0,
        },
        "limits": {},
        "issues": [],
    }


def test_context_preflight_reports_trimmed_context():
    from forum.context_preflight import build_context_preflight

    payload = build_context_preflight(
        "build api",
        context="abcdefghijklmnop",
        context_source="capsule",
        budget=ContextBudget(max_request_tokens=2),
    )

    assert payload["ready"] is True
    assert payload["context"] == {
        "source": "capsule",
        "action": "trimmed",
        "reason": "max_request_tokens",
        "original_tokens": 4,
        "admitted_tokens": 2,
        "tokens_saved": 2,
    }
    assert payload["limits"] == {"bytes_per_token": 4, "max_request_tokens": 2}
    assert payload["issues"] == ["capsule context would be trimmed before planning"]


def test_context_preflight_reports_omitted_context_as_not_ready():
    from forum.context_preflight import build_context_preflight

    payload = build_context_preflight(
        "build api",
        context="abcd",
        context_source="capsule",
        budget=ContextBudget(max_total_tokens=0),
    )

    assert payload["ready"] is False
    assert payload["context"]["action"] == "omitted"
    assert payload["context"]["reason"] == "max_total_tokens"
    assert payload["issues"] == ["capsule context would be omitted before planning"]


def test_context_preflight_text_is_concise():
    from forum.context_preflight import build_context_preflight, context_preflight_text

    payload = build_context_preflight(
        "build api",
        context="abcdefghijklmnop",
        context_source="capsule",
        budget=ContextBudget(max_request_tokens=2),
    )

    text = context_preflight_text(payload)

    assert "Forum context preflight" in text
    assert "ready: True" in text
    assert "request: 3 tokens" in text
    assert "context: capsule trimmed 4->2 tokens" in text
    assert "capsule context would be trimmed" in text


def test_context_preflight_recognizes_index_context_envelope_json():
    from forum.context_preflight import build_context_preflight, context_preflight_text

    context = """
    {
      "schema": "project-telos.context-envelope/v1",
      "verification_verdict": "MATCH",
      "retained": [{"name": "index"}, {"name": "forum"}],
      "omitted": [{"name": "docs", "reason": "outside_focus_or_budget"}],
      "budget": {"approx_tokens": 42, "token_budget": 100}
    }
    """

    payload = build_context_preflight("improve index", context=context, context_source="index")

    assert payload["context"]["structured"] == {
        "schema": "project-telos.context-envelope/v1",
        "verification_verdict": "MATCH",
        "retained": 2,
        "omitted": 1,
        "approx_tokens": 42,
        "token_budget": 100,
    }
    text = context_preflight_text(payload)
    assert "structured: project-telos.context-envelope/v1 verdict=MATCH retained=2 omitted=1 tokens=42/100" in text


def test_context_preflight_defaults_nullable_or_malformed_envelope_fields():
    from forum.context_preflight import build_context_preflight

    context = """
    {
      "schema": "project-telos.context-envelope/v1",
      "verification_verdict": "PARTIAL",
      "retained": null,
      "omitted": {"name": "not-a-list"},
      "budget": null
    }
    """

    payload = build_context_preflight("improve forum", context=context, context_source="index")

    assert payload["context"]["structured"] == {
        "schema": "project-telos.context-envelope/v1",
        "verification_verdict": "PARTIAL",
        "retained": 0,
        "omitted": 0,
        "approx_tokens": None,
        "token_budget": None,
    }
