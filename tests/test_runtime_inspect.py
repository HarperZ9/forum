from forum.roster import AgentSpec, Roster


def _roster():
    return Roster(
        (
            AgentSpec("docs", "support", "Docs", ("docs",), "cheap", "cli"),
            AgentSpec("backend", "engineering", "Backend", ("api",), "capable", "cli"),
            AgentSpec("foundry", "support", "Foundry", ("model",), "frontier", "cli"),
        )
    )


def test_inspect_runtime_reports_ready_tiers_and_roster_counts():
    from forum.runtime_descriptor import RuntimeExecutorSpec
    from forum.runtime_inspect import inspect_runtime

    default = RuntimeExecutorSpec("chat", "llama3", "config", {"model": "llama3"})
    tiers = {
        "cheap": RuntimeExecutorSpec("chat", "phi3", "config", {"model": "phi3"}),
        "capable": RuntimeExecutorSpec("cmd", "SubprocessExecutor", "cli", {"argv": "ollama run llama3"}),
    }

    payload = inspect_runtime(default, tiers, _roster())

    assert payload["schema"] == "forum.runtime.inspect/v1"
    assert payload["ready"] is True
    assert payload["default"] == {
        "kind": "chat",
        "id": "llama3",
        "source": "config",
        "detail": {"model": "llama3"},
    }
    assert payload["tiers"]["cheap"]["id"] == "phi3"
    assert payload["tiers"]["capable"]["source"] == "cli"
    assert payload["tiers"]["frontier"] == {
        "kind": "fallback",
        "id": "llama3",
        "source": "default",
        "detail": {"tier": "frontier"},
    }
    assert payload["roster"] == {
        "agents": 3,
        "tiers": {"cheap": 1, "capable": 1, "frontier": 1},
    }
    assert payload["issues"] == []


def test_inspect_runtime_reports_missing_executors():
    from forum.runtime_descriptor import RuntimeExecutorSpec
    from forum.runtime_inspect import inspect_runtime

    tiers = {
        "capable": RuntimeExecutorSpec("cmd", "SubprocessExecutor", "cli", {"argv": "model"}),
    }

    payload = inspect_runtime(None, tiers, _roster())

    assert payload["ready"] is False
    assert payload["default"] == {
        "kind": "missing",
        "id": "",
        "source": "none",
        "detail": {},
    }
    assert payload["tiers"]["cheap"]["kind"] == "missing"
    assert payload["tiers"]["frontier"]["kind"] == "missing"
    assert payload["issues"] == [
        "no default executor configured for control roles",
        "no executor configured for roster tier: cheap",
        "no executor configured for roster tier: frontier",
    ]


def test_runtime_inspect_text_summarizes_payload():
    from forum.runtime_inspect import runtime_inspect_text

    text = runtime_inspect_text({
        "ready": False,
        "default": {"kind": "missing", "id": "", "source": "none"},
        "tiers": {"cheap": {"kind": "missing", "id": "", "source": "none"}},
        "roster": {"agents": 1, "tiers": {"cheap": 1}},
        "issues": ["no default executor configured for control roles"],
    })

    assert "Forum runtime inspection" in text
    assert "ready: False" in text
    assert "default: missing" in text
    assert "cheap: missing" in text
    assert "no default executor configured" in text
