from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULES = ROOT / "src" / "cgnk_knowledge"
sys.path.insert(0, str(ROOT / "src"))

import cgnk_knowledge


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            result.add(prefix + str(node.module or ""))
        elif isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
    return result


def test_knowledge_projection_has_no_persistence_or_domain_dependency() -> None:
    imports = _imports(MODULES / "projection.py")
    assert not any("persistence" in name for name in imports)
    assert not any("internalization" in name for name in imports)
    assert not any(name.endswith("store") for name in imports)


def test_persistence_no_longer_imports_store_or_internalization() -> None:
    imports = _imports(MODULES / "persistence.py")
    assert ".store" not in imports
    assert ".internalization" not in imports


def test_public_projection_compatibility_api_is_preserved() -> None:
    assert callable(cgnk_knowledge.build_knowledge_index)
    assert callable(cgnk_knowledge.rebuild_pack_indexes)
    assert callable(cgnk_knowledge.load_legacy_project_knowledge)

