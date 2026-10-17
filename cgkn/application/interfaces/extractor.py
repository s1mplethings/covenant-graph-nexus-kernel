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
        return {"modules": thaw(self.modules), "functions": thaw(self.functions), "cli": thaw(self.cli), "unresolved": list(self.unresolved)}


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


def _call_assignment(tree: ast.AST) -> tuple[set[str], dict[str, str], dict[str, str]]:
    parsers: set[str] = set()
    subparser_groups: dict[str, str] = {}
    subcommands: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else node.target if isinstance(node, ast.AnnAssign) else None
        value = node.value
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Call):
            continue
        func = value.func
        if (isinstance(func, ast.Name) and func.id == "ArgumentParser") or (isinstance(func, ast.Attribute) and func.attr == "ArgumentParser"):
            parsers.add(target.id)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.attr == "add_subparsers":
            subparser_groups[target.id] = func.value.id
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.attr == "add_parser" and func.value.id in subparser_groups:
            command = _literal_string(value.args[0]) if value.args else None
            if command:
                parsers.add(target.id)
                subcommands[target.id] = command
    return parsers, subparser_groups, subcommands


def _argument(call: ast.Call, index: int) -> tuple[list[str], dict[str, Any], bool] | None:
    flags = [_literal_string(item) for item in call.args]
    if not flags or any(item is None for item in flags):
        return None
    values = [str(item) for item in flags]
    keywords = {item.arg: item.value for item in call.keywords if item.arg}
    action = _literal_string(keywords["action"]) if "action" in keywords else None
    takes_value = action not in {"store_true", "store_false", "count", "help", "version"}
    if values[0].startswith("-"):
        dest = _literal_string(keywords["dest"]) if "dest" in keywords else max(values, key=len).lstrip("-").replace("-", "_")
        return values, {"flags": values, "dest": dest, "takes_value": takes_value}, True
    nargs = _literal_string(keywords["nargs"]) if "nargs" in keywords else None
    return values, {"name": values[0], "index": index, "required": nargs not in {"?", "*"}}, False


def extract_interfaces(sources: Mapping[str, str]) -> ObservedInterfaceManifest:
    modules: dict[str, Any] = {}
    functions: dict[str, Any] = {}
    root_positionals: list[dict[str, Any]] = []
    root_options: dict[str, Any] = {}
    commands: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []
    cli_module: str | None = None
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
                offset = len(positional) - len(node.args.defaults)
                params = [{"name": arg.arg, "kind": "POSITIONAL_ONLY" if i < len(node.args.posonlyargs) else "POSITIONAL_OR_KEYWORD",
                           "required": i < offset, "default_present": i >= offset} for i, arg in enumerate(positional)]
                params.extend({"name": arg.arg, "kind": "KEYWORD_ONLY", "required": default is None, "default_present": default is not None}
                              for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults))
                functions[f"{module}.{node.name}"] = {"module": module, "name": node.name, "parameters": params,
                                                        "exported": not node.name.startswith("_") or node.name in imported_exports}
        if not path.endswith("/__main__.py"):
            continue
        cli_module = module.removesuffix(".__main__")
        parsers, _, subcommand_vars = _call_assignment(tree)
        parser_present = bool(parsers)
        per_parser_positionals: dict[str, list[dict[str, Any]]] = {name: [] for name in parsers}
        per_parser_options: dict[str, dict[str, Any]] = {name: {} for name in parsers}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument" or not isinstance(node.func.value, ast.Name):
                continue
            receiver = node.func.value.id
            if receiver not in parsers:
                continue
            item = _argument(node, len(per_parser_positionals[receiver]))
            if item is None:
                unresolved.append(f"dynamic_add_argument:{path}:{getattr(node, 'lineno', 0)}")
                continue
            flags, record, is_option = item
            if is_option:
                for flag in flags:
                    per_parser_options[receiver][flag] = record
            else:
                per_parser_positionals[receiver].append(record)
        for parser in parsers:
            per_parser_options[parser].setdefault("--help", {"flags": ["-h", "--help"], "dest": "help", "takes_value": False})
            per_parser_options[parser].setdefault("-h", per_parser_options[parser]["--help"])
        for parser, command in subcommand_vars.items():
            commands[command] = {"positionals": per_parser_positionals[parser], "options": per_parser_options[parser]}
        root_candidates = sorted(parsers - set(subcommand_vars))
        if parser_present and root_candidates:
            root_positionals = per_parser_positionals[root_candidates[0]]
            root_options = per_parser_options[root_candidates[0]]
    cli = {"entrypoint": ["python", "-m", cli_module] if cli_module else [], "positionals": root_positionals,
           "options": root_options, "subcommands": commands}
    return ObservedInterfaceManifest(FrozenMapping(modules), FrozenMapping(functions), FrozenMapping(cli), tuple(sorted(unresolved)))
