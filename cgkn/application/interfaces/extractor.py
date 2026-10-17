from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping

from cgkn.application.requirements.obligation import FrozenMapping, thaw


@dataclass(frozen=True)
class ObservedInterfaceManifest:
    modules: FrozenMapping
    functions: FrozenMapping
    cli: FrozenMapping
    unresolved: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "modules": thaw(self.modules), "functions": thaw(self.functions),
            "cli": thaw(self.cli), "unresolved": list(self.unresolved),
        }


def _literal_string(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _module_name(path: str) -> str | None:
    normalized = PurePosixPath(path.replace("\\", "/"))
    if normalized.suffix != ".py":
        return None
    parts = list(normalized.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or None


def extract_interfaces(sources: Mapping[str, str]) -> ObservedInterfaceManifest:
    modules: dict[str, Any] = {}
    functions: dict[str, Any] = {}
    cli_positionals: list[dict[str, Any]] = []
    cli_options: dict[str, Any] = {}
    unresolved: list[str] = []
    cli_entrypoint = False
    for raw_path, content in sorted(sources.items()):
        path = raw_path.replace("\\", "/")
        module = _module_name(path)
        if module is None:
            continue
        modules[module] = {"path": path, "exists": True}
        try:
            tree = ast.parse(content, filename=path)
        except SyntaxError:
            unresolved.append(f"syntax:{path}")
            continue
        imported_exports: set[str] = set()
        if path.endswith("/__init__.py"):
            for node in tree.body:
                if isinstance(node, ast.ImportFrom):
                    imported_exports.update(alias.asname or alias.name for alias in node.names)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                positional = list(node.args.posonlyargs) + list(node.args.args)
                default_offset = len(positional) - len(node.args.defaults)
                params = []
                for index, arg in enumerate(positional):
                    kind = "POSITIONAL_ONLY" if index < len(node.args.posonlyargs) else "POSITIONAL_OR_KEYWORD"
                    params.append({"name": arg.arg, "kind": kind, "required": index < default_offset, "default_present": index >= default_offset})
                for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
                    params.append({"name": arg.arg, "kind": "KEYWORD_ONLY", "required": default is None, "default_present": default is not None})
                functions[f"{module}.{node.name}"] = {
                    "module": module, "name": node.name, "parameters": params,
                    "exported": not node.name.startswith("_") or node.name in imported_exports,
                }
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
                flags = [_literal_string(item) for item in node.args]
                if not flags or any(item is None for item in flags):
                    unresolved.append(f"dynamic_add_argument:{path}:{getattr(node, 'lineno', 0)}")
                    continue
                values = [str(item) for item in flags]
                keywords = {item.arg: item.value for item in node.keywords if item.arg}
                action = _literal_string(keywords["action"]) if "action" in keywords else None
                takes_value = action not in {"store_true", "store_false", "count", "help", "version"}
                if values[0].startswith("-"):
                    dest = _literal_string(keywords["dest"]) if "dest" in keywords else max(values, key=len).lstrip("-").replace("-", "_")
                    record = {"flags": values, "dest": dest, "takes_value": takes_value}
                    for flag in values:
                        cli_options[flag] = record
                else:
                    cli_positionals.append({"name": values[0], "index": len(cli_positionals), "required": True})
        if path == "csv_cleaner/__main__.py":
            cli_entrypoint = True
            if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ArgumentParser" for node in ast.walk(tree)) or any(
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "ArgumentParser" for node in ast.walk(tree)
            ):
                cli_options.setdefault("--help", {"flags": ["-h", "--help"], "dest": "help", "takes_value": False})
                cli_options.setdefault("-h", cli_options["--help"])
    cli = {
        "entrypoint": ["python", "-m", "csv_cleaner"] if cli_entrypoint else [],
        "positionals": cli_positionals,
        "options": cli_options,
    }
    return ObservedInterfaceManifest(FrozenMapping(modules), FrozenMapping(functions), FrozenMapping(cli), tuple(sorted(unresolved)))
