#!/usr/bin/env python3
"""Deterministic, read-only inventory for semantics-preserving architecture diet work."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import pathlib
import subprocess
import tarfile
from collections import Counter, defaultdict
from functools import lru_cache
from typing import Any, Iterable, Mapping


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = "7fafb7471ebfda9a931fc1b8fb8fb3e40185a1e4"
PRODUCTION_PREFIXES = ("cgkn/", "src/cgnk_knowledge/", "src/cgkn_project_management/", "contracts/")
PRODUCTION_FILES = {
    "plugins/cgkn/scripts/cgkn_mcp_server.py",
    "scripts/canonical_repo_publish.py",
    "scripts/codex_conversation.py",
    "scripts/local_agent_actions.py",
    "scripts/local_packager.py",
    "scripts/provider_jobs.py",
    "scripts/public_delivery_gate.py",
    "scripts/real_test_execution.py",
    "scripts/run_codex_conversation_generation.py",
    "scripts/run_local_pipeline.py",
    "scripts/run_local_pipeline_impl.py",
}
SURFACE_SPEC_PREFIXES = ("specs/modules/", "specs/flows/", "specs/artifacts/")
SCHEMA_PREFIXES = ("schemas/",)
SCHEMA_SUFFIXES = (".schema.json",)
CONVERSATION_SURFACE_NAMES = {
    "CONVERSATION_COMPONENT_SPEC",
    "CONVERSATION_ANSWER_SCHEMA",
    "CONTEXT_POLICY",
    "RETRIEVAL_POLICY",
    "MODEL_CONFIG",
    "ConversationRequest",
    "ConversationResponse",
    "ConversationStatus",
}


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout


def _sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _is_production(path: str) -> bool:
    return path in PRODUCTION_FILES or path.endswith(".py") and path.startswith(PRODUCTION_PREFIXES)


def _paths(revision: str | None) -> tuple[str, ...]:
    if revision:
        return tuple(line for line in _git("ls-tree", "-r", "--name-only", revision).splitlines() if line)
    return tuple(
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(ROOT).parts
    )


def _reader(revision: str | None):
    cache: dict[str, str] = {}
    if revision:
        completed = subprocess.run(
            ["git", "archive", "--format=tar", revision], cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if completed.returncode:
            raise RuntimeError(completed.stderr.decode("utf-8", errors="replace").strip() or "git archive failed")
        with tarfile.open(fileobj=io.BytesIO(completed.stdout), mode="r:") as archive:
            for member in archive.getmembers():
                if member.isfile() and member.name.endswith((".py", ".json", ".md", ".yaml", ".yml", ".toml", ".txt")):
                    extracted = archive.extractfile(member)
                    if extracted is not None:
                        cache[member.name] = extracted.read().decode("utf-8", errors="strict")

    def read(path: str) -> str:
        if path not in cache:
            cache[path] = (ROOT / path).read_text(encoding="utf-8")
        return cache[path]

    return read


def _module_name(path: str) -> str:
    raw = path[:-3] if path.endswith(".py") else path
    parts = raw.split("/")
    if parts[0] == "src":
        parts = parts[1:]
    elif parts[:3] == ["plugins", "cgkn", "scripts"]:
        parts = parts[3:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = [item.arg for item in (*node.args.posonlyargs, *node.args.args)]
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    args.extend(item.arg for item in node.args.kwonlyargs)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)
    return f"{node.name}({','.join(args)})"


def _module_record(path: str, source: str) -> dict[str, Any]:
    tree = ast.parse(source, filename=path)
    classes: list[str] = []
    functions: list[str] = []
    dataclasses: list[str] = []
    signatures: list[str] = []
    project_imports: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            functions.append(node.name)
            signatures.append(_signature(node))
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            classes.append(node.name)
            signatures.append(node.name)
            if any(
                isinstance(item, ast.Name) and item.id == "dataclass"
                or isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "dataclass"
                for item in node.decorator_list
            ):
                dataclasses.append(node.name)
            signatures.extend(
                f"{node.name}.{_signature(item)}"
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("_")
            )
        elif isinstance(node, ast.ImportFrom) and (
            node.level or (node.module or "").startswith(("cgkn", "cgnk_knowledge", "cgkn_project_management"))
        ):
            project_imports.extend(
                item.asname or item.name
                for item in node.names
                if not (item.asname or item.name).startswith("_")
            )
    all_exports: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                value = ()
            all_exports = [str(item) for item in value]
    purpose = (ast.get_docstring(tree) or "").strip().splitlines()
    return {
        "path": path,
        "module": _module_name(path),
        "purpose": purpose[0] if purpose else f"Implements {_module_name(path)}.",
        "public_symbols": sorted((*classes, *functions)),
        "public_signatures": sorted(signatures),
        "public_project_imports": sorted(project_imports),
        "explicit_exports": sorted(all_exports),
        "public_class_count": len(classes),
        "public_function_count": len(functions),
        "dataclass_count": len(dataclasses),
        "loc": len(source.splitlines()),
        "tree": tree,
    }


def _imports(module: str, tree: ast.AST) -> set[str]:
    rows: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            rows.update(item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parent = module.split(".")[:-1]
                keep = max(0, len(parent) - node.level + 1)
                prefix = parent[:keep]
                if node.module:
                    prefix.extend(node.module.split("."))
                target = ".".join(prefix)
            else:
                target = node.module or ""
            if target:
                rows.add(target)
    return rows


def _classification(path: str) -> str:
    if path.startswith("contracts/") or path.endswith("/__init__.py"):
        return "PRODUCTION_CONTRACT"
    if path.startswith("src/cgkn_project_management/"):
        return "GOVERNANCE"
    return "PRODUCTION_RUNTIME"


def _authority_map(read, paths: set[str]) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = defaultdict(list)
    architecture = json.loads(read("governance/current_architecture.json"))
    for name, ref in architecture.get("declared_authorities", {}).items():
        module = str(ref).split(":", 1)[0]
        candidate = module if module.endswith(".py") else module.replace(".", "/") + ".py"
        if candidate in paths:
            rows[candidate].append(name)
    return rows


def _nearest_module(name: str, known: Mapping[str, str]) -> str | None:
    target = name
    while target:
        if target in known:
            return target
        target = target.rsplit(".", 1)[0] if "." in target else ""
    return None


def _graph_metrics(adjacency: Mapping[str, set[str]]) -> tuple[int, list[list[str]]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indexes: dict[str, int] = {}
    lows: dict[str, int] = {}
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = lows[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for child in adjacency[node]:
            if child not in indexes:
                visit(child)
                lows[node] = min(lows[node], lows[child])
            elif child in on_stack:
                lows[node] = min(lows[node], indexes[child])
        if lows[node] == indexes[node]:
            component: list[str] = []
            while True:
                child = stack.pop()
                on_stack.remove(child)
                component.append(child)
                if child == node:
                    break
            components.append(component)

    for module in adjacency:
        if module not in indexes:
            visit(module)
    component_by_module = {module: number for number, group in enumerate(components) for module in group}
    dag = {number: set() for number in range(len(components))}
    for module, children in adjacency.items():
        for child in children:
            if component_by_module[module] != component_by_module[child]:
                dag[component_by_module[module]].add(component_by_module[child])

    @lru_cache(maxsize=None)
    def depth(number: int) -> int:
        return 1 + max((depth(child) for child in dag[number]), default=0)

    return max((depth(number) for number in dag), default=0), [sorted(group) for group in components if len(group) > 1]


def _file_hashes(paths: Iterable[str], read) -> dict[str, str]:
    return {
        path: "sha256:" + hashlib.sha256(read(path).replace("\r\n", "\n").encode("utf-8")).hexdigest()
        for path in sorted(paths)
    }


def _mcp_tools(source: str) -> list[str]:
    tree = ast.parse(source)
    return sorted({
        str(node.args[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "tool_definition"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    })


def _cli_profiles(path: str, source: str) -> list[str]:
    tree = ast.parse(source)
    constants: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    rows: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not any(isinstance(arg, ast.Constant) and arg.value == "--profile" for arg in node.args):
            continue
        for keyword in node.keywords:
            if keyword.arg != "choices":
                continue
            try:
                value = ast.literal_eval(keyword.value)
            except (ValueError, TypeError):
                value = constants.get(keyword.value.id, ()) if isinstance(keyword.value, ast.Name) else ()
            rows.update(str(item) for item in value)
    return sorted(rows)


def _conversation_contract(source: str) -> list[str]:
    tree = ast.parse(source)
    rows: list[str] = []
    for node in tree.body:
        name = node.name if isinstance(node, ast.ClassDef) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        if name in CONVERSATION_SURFACE_NAMES:
            rows.append(ast.dump(node, annotate_fields=True, include_attributes=False))
    return sorted(rows)


@lru_cache(maxsize=4)
def audit(revision: str | None = None) -> dict[str, Any]:
    paths = set(_paths(revision))
    read = _reader(revision)
    production_paths = sorted(path for path in paths if _is_production(path))
    records = {path: _module_record(path, read(path)) for path in production_paths}
    module_paths = {record["module"]: path for path, record in records.items() if record["module"]}
    adjacency: dict[str, set[str]] = {module: set() for module in module_paths}
    incoming: dict[str, set[str]] = {module: set() for module in module_paths}
    for path, record in records.items():
        module = record["module"]
        if not module:
            continue
        for imported in _imports(module, record.pop("tree")):
            target = _nearest_module(imported, module_paths)
            if target and target != module:
                adjacency[module].add(target)
                incoming[target].add(module)
    authority = _authority_map(read, paths)
    test_sources = {path: read(path) for path in paths if path.startswith("tests/") and path.endswith(".py")}
    benchmark_sources = {path: read(path) for path in paths if path.startswith("benchmarks/") and path.endswith((".py", ".json", ".md"))}
    max_depth, cyclic = _graph_metrics(adjacency)
    inventory = []
    for path, record in sorted(records.items()):
        module = record["module"]
        dynamic_refs = sum(source.count(module) for source in (*test_sources.values(), *benchmark_sources.values()))
        record.update({
            "authority": sorted(authority.get(path, ())) or ["NONE_DECLARED"],
            "classification": _classification(path),
            "incoming_dependencies": sorted(incoming.get(module, ())),
            "outgoing_dependencies": sorted(adjacency.get(module, ())),
            "runtime_usage": "RUNTIME_REFERENCED" if incoming.get(module) else "ENTRYPOINT_OR_DYNAMIC" if path in PRODUCTION_FILES or path.endswith("/__init__.py") else "NO_STATIC_RUNTIME_INCOMING",
            "test_usage": sum(source.count(module) for source in test_sources.values()),
            "benchmark_only_usage": sum(source.count(module) for source in benchmark_sources.values()),
            "dynamic_reference_count": dynamic_refs,
            "candidate_status": "KEEP" if authority.get(path) or incoming.get(module) or dynamic_refs else "UNCERTAIN",
        })
        inventory.append(record)
    spec_paths = {path for path in paths if path.startswith(SURFACE_SPEC_PREFIXES) and path.endswith(".json")}
    schema_paths = {
        path for path in paths
        if path.startswith(SCHEMA_PREFIXES) and path.endswith(".json")
        or path.startswith("contracts/") and path.endswith(SCHEMA_SUFFIXES)
    }
    registry_rows = _file_hashes(spec_paths, read)
    schema_rows = _file_hashes(schema_paths, read)
    cli_rows = {
        path: _cli_profiles(path, read(path))
        for path in paths
        if path.startswith("scripts/") and path.endswith(".py") and "run_" in pathlib.PurePosixPath(path).name
    }
    cli_rows = {path: values for path, values in cli_rows.items() if values}
    mcp_tools = _mcp_tools(read("plugins/cgkn/scripts/cgkn_mcp_server.py"))
    public_api = {
        record["module"]: {
            "symbols": record["public_symbols"],
            "signatures": record["public_signatures"],
            "project_imports": record["public_project_imports"],
            "exports": record["explicit_exports"],
        }
        for record in inventory
    }
    conversation_contract = _conversation_contract(read("cgkn/application/conversation/service.py"))
    knowledge_formats = {path: schema_rows[path] for path in schema_rows if "knowledge" in path or "conversation" in path}
    surface = {
        "public_api": public_api,
        "component_and_artifact_specs": registry_rows,
        "mcp_tools": mcp_tools,
        "cli_profiles": cli_rows,
        "knowledge_formats": knowledge_formats,
        "conversation_contract": conversation_contract,
    }
    classifications = Counter(record["classification"] for record in inventory)
    return {
        "kind": "CGKNArchitectureDietAudit",
        "schema_version": "1.0",
        "revision": revision or "WORKING_TREE",
        "baseline": BASELINE,
        "metrics": {
            "production_loc": sum(record["loc"] for record in inventory),
            "production_python_files": len(inventory),
            "production_module_count": len(inventory),
            "public_classes": sum(record["public_class_count"] for record in inventory),
            "public_functions": sum(record["public_function_count"] for record in inventory),
            "dataclass_schema_classes": sum(record["dataclass_count"] for record in inventory),
            "runtime_dependency_edges": sum(len(children) for children in adjacency.values()),
            "maximum_import_depth": max_depth,
            "cyclic_scc_count": len(cyclic),
            "cyclic_sccs": cyclic,
            "classification_counts": dict(sorted(classifications.items())),
        },
        "surface": surface,
        "public_surface_hash": _sha(surface),
        "registry_hash": _sha(registry_rows),
        "schema_hash": _sha(schema_rows),
        "module_inventory": inventory,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = audit(args.revision)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        output = (ROOT / args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
