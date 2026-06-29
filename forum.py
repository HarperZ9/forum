from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> None:
    src = Path(__file__).resolve().parent / "src"
    if src.exists():
        sys.path.insert(0, str(src))
    runpy.run_module("forum", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
