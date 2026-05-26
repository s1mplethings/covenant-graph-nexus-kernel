from __future__ import annotations

import ast
import pathlib
from typing import Any

from cgnk_core.diagnostics import (
    CGNK_PROJECT_GRAPH_AST_PARSE_FAILED,
    CGNK_PROJECT_GRAPH_BUILD_FAILED,
    CGNK_PROJECT_GRAPH_FORBIDDEN_PATH,
    CGNK_PROJECT_GRAPH_INVALID_SNAPSHOT,
    Diagnostic,
)

from .contracts import INPUT_ARTIFACT_REF, MODULE_REF, OUTPUT_ARTIFACT_REF

FORBIDDEN_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "final_output",
    "project_output",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
}
FORBIDDEN_SUFFIXES = {".sqlite", ".db", ".zip"}
PROJECT_MARKERS = ("pyproject.toml", "setup.py", "package.json", "requirements.txt", "README.md")


def build_project_graph(snapshot: dict[str, Any], parse_python_imports: bool = True) -> dict[str, Any]:
    diagnostics: list[Diagnostic] = []
    if not _valid_snapshot(snapshot):
        diagnostics.append(
            Diagnostic(
                CGNK_PROJECT_GRAPH_INVALID_SNAPSHOT,
                "error",
                "$.snapshot",
                "Project graph input must be a ProjectSnapshot-like artifact",
                expected=INPUT_ARTIFACT_REF,
                actual=snapshot.get("artifact_ref") if isinstance(snapshot, dict) else type(snapshot).__name__,
                involved_ref=MODULE_REF,
            )
        )
        return {"ok": False, "graph": None, "diagnostics": [d.as_dict() for d in diagnostics]}

    root = pathlib.Path(snapshot.get("metadata", {}).get("root", "")).resolve()
    files = []
    for row in sorted(snapshot.get("files", []), key=lambda item: item.get("path", "")):
        rel = row.get("path", "")
        if _is_forbidden(rel):
            diagnostics.append(Diagnostic(CGNK_PROJECT_GRAPH_FORBIDDEN_PATH, "warning", "$.snapshot.files", "Forbidden path excluded from project graph", expected="allowed project source path", actual=rel, involved_ref=OUTPUT_ARTIFACT_REF, source={"path": rel}))
            continue
        files.append(row)

    try:
        graph = _build_graph(snapshot, files, root, parse_python_imports, diagnostics)
    except Exception as exc:  # pragma: no cover - defensive boundary
        diagnostics.append(Diagnostic(CGNK_PROJECT_GRAPH_BUILD_FAILED, "error", "$.graph", "Project graph build failed", actual=str(exc), involved_ref=MODULE_REF))
        return {"ok": False, "graph": None, "diagnostics": [d.as_dict() for d in diagnostics]}

    ok = not any(d.severity == "error" for d in diagnostics)
    return {"ok": ok, "graph": graph, "diagnostics": [d.as_dict() for d in diagnostics]}


def _valid_snapshot(snapshot: dict[str, Any]) -> bool:
    return (
        isinstance(snapshot, dict)
        and snapshot.get("kind") == "ProjectSnapshot"
        and snapshot.get("artifact_ref") == INPUT_ARTIFACT_REF
        and isinstance(snapshot.get("metadata"), dict)
        and isinstance(snapshot.get("files"), list)
    )


def _build_graph(
    snapshot: dict[str, Any],
    files: list[dict[str, Any]],
    root: pathlib.Path,
    parse_python_imports: bool,
    diagnostics: list[Diagnostic],
) -> dict[str, Any]:
    node_map: dict[str, dict[str, Any]] = {}
    edge_map: dict[tuple[str, str, str], dict[str, str]] = {}
    marker_paths = {marker: False for marker in PROJECT_MARKERS}
    has_tests_dir = False
    package_dirs = _package_dirs(files)

    _add_node(node_map, {"id": "dir:.", "kind": "directory", "path": ".", "package": "." in package_dirs})
    for file_row in files:
        rel = file_row["path"]
        path = pathlib.PurePosixPath(rel)
        if path.parts and path.parts[0] == "tests":
            has_tests_dir = True
        if rel in marker_paths:
            marker_paths[rel] = True
        _add_directory_chain(node_map, edge_map, path.parent.as_posix(), package_dirs)
        file_id = f"file:{rel}"
        _add_node(
            node_map,
            {
                "id": file_id,
                "kind": "file",
                "path": rel,
                "classification": _classify_file(rel),
                "size_bytes": file_row.get("size_bytes", 0),
                "sha256": file_row.get("sha256"),
            },
        )
        parent = _dir_id(path.parent.as_posix())
        _add_edge(edge_map, parent, file_id, "contains")
        if parse_python_imports and rel.endswith(".py"):
            _add_python_import_edges(root, rel, node_map, edge_map, diagnostics)

    markers = {**marker_paths, "tests/": has_tests_dir}
    return {
        "kind": "ProjectGraph",
        "schema_version": "1",
        "artifact_ref": OUTPUT_ARTIFACT_REF,
        "module_ref": MODULE_REF,
        "source_snapshot": {
            "artifact_ref": snapshot.get("artifact_ref"),
            "file_count": snapshot.get("metadata", {}).get("file_count"),
            "root_name": snapshot.get("metadata", {}).get("root_name"),
        },
        "metadata": {
            "root": snapshot.get("metadata", {}).get("root"),
            "node_count": len(node_map),
            "edge_count": len(edge_map),
            "project_markers": markers,
        },
        "nodes": sorted(node_map.values(), key=lambda row: row["id"]),
        "edges": sorted(edge_map.values(), key=lambda row: (row["source"], row["target"], row["type"])),
        "adjacency": _adjacency(edge_map),
        "diagnostics": [d.as_dict() for d in diagnostics],
    }


def _add_directory_chain(node_map: dict[str, dict[str, Any]], edge_map: dict[tuple[str, str, str], dict[str, str]], parent_path: str, package_dirs: set[str]) -> None:
    if parent_path in {"", "."}:
        return
    parts = pathlib.PurePosixPath(parent_path).parts
    current = "."
    for part in parts:
        previous = current
        current = part if current == "." else f"{current}/{part}"
        node_id = _dir_id(current)
        _add_node(node_map, {"id": node_id, "kind": "directory", "path": current, "package": current in package_dirs})
        _add_edge(edge_map, _dir_id(previous), node_id, "contains")


def _package_dirs(files: list[dict[str, Any]]) -> set[str]:
    packages = set()
    for row in files:
        rel = row.get("path", "")
        if rel.endswith("__init__.py"):
            parent = pathlib.PurePosixPath(rel).parent.as_posix()
            packages.add("." if parent == "." else parent)
        if rel == "package.json":
            packages.add(".")
    return packages


def _add_python_import_edges(root: pathlib.Path, rel: str, node_map: dict[str, dict[str, Any]], edge_map: dict[tuple[str, str, str], dict[str, str]], diagnostics: list[Diagnostic]) -> None:
    path = root / pathlib.PurePosixPath(rel)
    if not path.is_file():
        return
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=rel)
    except SyntaxError as exc:
        diagnostics.append(Diagnostic(CGNK_PROJECT_GRAPH_AST_PARSE_FAILED, "warning", f"$.files[{rel}]", "Python import scan skipped because AST parse failed", actual=str(exc), involved_ref=OUTPUT_ARTIFACT_REF, source={"path": rel}))
        return
    except OSError as exc:
        diagnostics.append(Diagnostic(CGNK_PROJECT_GRAPH_BUILD_FAILED, "warning", f"$.files[{rel}]", "Python import scan skipped because file could not be read", actual=str(exc), involved_ref=OUTPUT_ARTIFACT_REF, source={"path": rel}))
        return
    source_id = f"file:{rel}"
    for module in sorted(_imports_from_tree(tree)):
        import_id = f"import:{module}"
        _add_node(node_map, {"id": import_id, "kind": "import_module", "name": module})
        _add_edge(edge_map, source_id, import_id, "imports")


def _imports_from_tree(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def _classify_file(rel: str) -> str:
    path = pathlib.PurePosixPath(rel)
    name = path.name.lower()
    suffix = path.suffix.lower()
    if any(part in {"tests", "test"} for part in path.parts) or name.startswith("test_") or name.endswith("_test.py"):
        return "test"
    if name in {"readme.md", "readme.rst"} or suffix in {".md", ".rst", ".txt"}:
        return "documentation"
    if name in {"pyproject.toml", "setup.py", "package.json", "requirements.txt"} or suffix in {".toml", ".yaml", ".yml", ".ini", ".cfg"}:
        return "config"
    if suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h", ".hpp", ".rs", ".go"}:
        return "source"
    if suffix in {".json", ".csv", ".tsv", ".xml"}:
        return "data"
    return "unknown"


def _is_forbidden(rel: str) -> bool:
    path = pathlib.PurePosixPath(rel)
    parts = set(path.parts)
    if parts & FORBIDDEN_DIRS:
        return True
    if path.suffix.lower() in FORBIDDEN_SUFFIXES:
        return True
    return False


def _add_node(node_map: dict[str, dict[str, Any]], node: dict[str, Any]) -> None:
    node_map[node["id"]] = {key: value for key, value in node.items() if value is not None}


def _add_edge(edge_map: dict[tuple[str, str, str], dict[str, str]], source: str, target: str, edge_type: str) -> None:
    edge_map[(source, target, edge_type)] = {"source": source, "target": target, "type": edge_type}


def _dir_id(path: str) -> str:
    return "dir:." if path in {"", "."} else f"dir:{path}"


def _adjacency(edge_map: dict[tuple[str, str, str], dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    adjacency: dict[str, list[dict[str, str]]] = {}
    for edge in sorted(edge_map.values(), key=lambda row: (row["source"], row["target"], row["type"])):
        adjacency.setdefault(edge["source"], []).append({"target": edge["target"], "type": edge["type"]})
    return adjacency
