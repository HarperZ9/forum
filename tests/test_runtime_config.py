import pytest

from forum.chat_executor import ChatExecutor
from forum.executor import SubprocessExecutor


def test_runtime_config_builds_default_and_tier_chat_executors(tmp_path):
    from forum.runtime_config import executors_from_runtime_config

    config = tmp_path / "forum-runtime.toml"
    config.write_text(
        """
[runtime.default]
chat_url = "http://base/v1/chat/completions"
model = "base-local"
api_key_env = "BASE_MODEL_KEY"

[runtime.tiers.cheap]
chat_url = "http://cheap/v1/chat/completions"
model = "phi3"

[runtime.tiers.frontier]
chat_url = "http://frontier/v1/chat/completions"
model = "qwen-coder"
""",
        encoding="utf-8",
    )

    base, tiers = executors_from_runtime_config(config)

    assert isinstance(base, ChatExecutor)
    assert base.model_id == "base-local"
    assert base._base_url == "http://base/v1/chat/completions"
    assert base._api_key_env == "BASE_MODEL_KEY"
    assert isinstance(tiers["cheap"], ChatExecutor)
    assert tiers["cheap"].model_id == "phi3"
    assert tiers["cheap"]._base_url == "http://cheap/v1/chat/completions"
    assert isinstance(tiers["frontier"], ChatExecutor)
    assert tiers["frontier"].model_id == "qwen-coder"


def test_runtime_config_builds_command_executors_and_preserves_windows_paths(
    monkeypatch, tmp_path
):
    import forum.runtime_config as runtime_config
    from forum.command_split import split_command

    monkeypatch.setattr(
        runtime_config,
        "split_command",
        lambda cmd: split_command(cmd, os_name="nt"),
    )
    config = tmp_path / "forum-runtime.toml"
    config.write_text(
        r"""
[runtime.tiers.capable]
cmd = 'C:\Tools\model.exe C:\tmp\adapter.py'
""",
        encoding="utf-8",
    )

    base, tiers = runtime_config.executors_from_runtime_config(config)

    assert base is None
    assert isinstance(tiers["capable"], SubprocessExecutor)
    assert tiers["capable"]._command == [
        r"C:\Tools\model.exe",
        r"C:\tmp\adapter.py",
    ]


def test_runtime_config_rejects_unknown_tier(tmp_path):
    from forum.runtime_config import executors_from_runtime_config

    config = tmp_path / "forum-runtime.toml"
    config.write_text(
        """
[runtime.tiers.premium]
cmd = "model"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown runtime tier: premium"):
        executors_from_runtime_config(config)
