import ast
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "forum.interop.json"


def _load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _repo_file(relative: str) -> Path:
    assert relative
    assert "\\" not in relative
    path = Path(relative)
    assert not path.is_absolute()
    assert ".." not in path.parts
    resolved = (ROOT / path).resolve()
    assert resolved.is_relative_to(ROOT.resolve())
    assert resolved.is_file(), relative
    return resolved


def _source_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.ClassDef, ast.FunctionDef))
    }


def _assert_repo_source_pointer(pointer: str) -> None:
    relative, symbol = pointer.split(":", 1)
    path = _repo_file(relative)
    assert symbol in _source_symbols(path), pointer


def _python_module_file(module: str) -> Path:
    parts = module.split(".")
    assert parts
    assert all(part.isidentifier() for part in parts), module
    source_file = Path("src", *parts).with_suffix(".py")
    if (ROOT / source_file).is_file():
        return _repo_file(source_file.as_posix())
    return _repo_file(Path("src", *parts, "__init__.py").as_posix())


def _assert_python_pointer(pointer: str) -> None:
    module, symbol = pointer.split(":", 1)
    path = _python_module_file(module)
    assert symbol in _source_symbols(path), pointer


def test_interop_manifest_declares_context_envelope_consumer_and_evidence():
    manifest = _load_manifest()
    consumers = {port["capability"]: port for port in manifest["consumes"]}

    assert consumers["project-telos.context-envelope/v1"]["module"] == (
        "src/forum/context_preflight.py:_index_context_envelope_summary"
    )
    assert {
        "src/forum/context_capsule.py",
        "src/forum/context_preflight.py",
    }.issubset(manifest["evidence"])


def test_interop_manifest_preserves_existing_capabilities():
    manifest = _load_manifest()
    emitted = [port["capability"] for port in manifest["emits"]]
    consumed = [port["capability"] for port in manifest["consumes"]]

    assert len(emitted) == len(set(emitted))
    assert set(emitted) == {
        "forum.context-capsule/v1",
        "forum.flight-recorder/1",
        "project-telos.action-receipt/v1",
        "project-telos.flagship-action/v1",
    }
    assert len(consumed) == len(set(consumed))
    assert set(consumed) == {
        "external-agent-trace/1",
        "project-telos.context-envelope/v1",
    }


def test_interop_manifest_pointers_are_source_grounded():
    manifest = _load_manifest()
    invoke = manifest["invoke"]

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    cli = invoke["cli"]
    assert cli in project["scripts"]
    _assert_python_pointer(project["scripts"][cli])
    _assert_python_pointer(invoke["mcp_server"])
    _python_module_file(invoke["python_import"])

    for side in ("emits", "consumes"):
        for port in manifest[side]:
            _assert_repo_source_pointer(port["module"])
    for relative in manifest["evidence"]:
        _repo_file(relative)
