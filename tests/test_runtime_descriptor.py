import pytest


def test_descriptor_from_config_reports_chat_and_command_specs(tmp_path):
    from forum.runtime_descriptor import descriptor_from_config

    config = tmp_path / "forum-runtime.toml"
    config.write_text(
        """
[runtime.default]
chat_url = "http://base/v1/chat/completions"
model = "llama3"
api_key_env = "BASE_MODEL_KEY"

[runtime.tiers.cheap]
chat_url = "http://cheap/v1/chat/completions"
model = "phi3"

[runtime.tiers.capable]
cmd = "ollama run llama3"
""",
        encoding="utf-8",
    )

    default, tiers = descriptor_from_config(config)

    assert default is not None
    assert default.kind == "chat"
    assert default.identity == "llama3"
    assert default.source == "config"
    assert default.detail == {
        "base_url": "http://base/v1/chat/completions",
        "model": "llama3",
        "api_key_env": "BASE_MODEL_KEY",
    }
    assert tiers["cheap"].kind == "chat"
    assert tiers["cheap"].identity == "phi3"
    assert tiers["cheap"].detail["base_url"] == "http://cheap/v1/chat/completions"
    assert tiers["capable"].kind == "cmd"
    assert tiers["capable"].identity == "SubprocessExecutor"
    assert tiers["capable"].detail == {"argv": "ollama run llama3"}


def test_descriptor_from_config_reuses_runtime_config_validation(tmp_path):
    from forum.runtime_descriptor import descriptor_from_config

    config = tmp_path / "forum-runtime.toml"
    config.write_text(
        """
[runtime.tiers.premium]
cmd = "model"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown runtime tier: premium"):
        descriptor_from_config(config)


def test_cli_default_descriptor_reports_api_default_model():
    from argparse import Namespace

    from forum.runtime_descriptor import cli_default_descriptor

    spec = cli_default_descriptor(
        Namespace(chat_url=None, api=True, model=None, api_key_env=None, cmd=None)
    )

    assert spec is not None
    assert spec.kind == "api"
    assert spec.identity == "claude-sonnet-4-6"
    assert spec.detail == {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "api_key_env": "ANTHROPIC_API_KEY",
    }
