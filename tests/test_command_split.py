from forum.command_split import split_command


def test_split_command_preserves_windows_paths():
    assert split_command(
        r"C:\Tools\model.exe C:\tmp\adapter.py",
        os_name="nt",
    ) == [r"C:\Tools\model.exe", r"C:\tmp\adapter.py"]


def test_split_command_uses_posix_parsing_by_default_on_non_windows():
    assert split_command(
        r"ollama run 'model name'",
        os_name="posix",
    ) == ["ollama", "run", "model name"]
