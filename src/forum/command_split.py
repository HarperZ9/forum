from __future__ import annotations

import os
import shlex


def split_command(cmd: str, *, os_name: str | None = None) -> list[str]:
    """Split an executor command using Windows parsing only for Windows targets."""
    platform = os.name if os_name is None else os_name
    return shlex.split(cmd, posix=platform != "nt")
