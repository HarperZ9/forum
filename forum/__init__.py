from __future__ import annotations

from pathlib import Path

# Source-checkout bridge: installed packages are still discovered from src/ by
# pyproject.toml, while `python -m forum` from the repo root can find them too.
_src_package = Path(__file__).resolve().parents[1] / "src" / "forum"
if _src_package.exists():
    __path__.insert(0, str(_src_package))
    _src_init = _src_package / "__init__.py"
    exec(compile(_src_init.read_text(encoding="utf-8"), str(_src_init), "exec"))
