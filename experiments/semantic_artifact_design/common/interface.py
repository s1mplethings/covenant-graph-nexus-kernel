from __future__ import annotations

import ast
import pathlib
from dataclasses import dataclass
from typing import Any, Mapping

from .canonical import canonical_hash


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
    args = [item.arg for item in (*node.args.posonlyargs, *node.args.args)]
    defaults = [None] * (len(args) - len(node.args.defaults)) + [ast.unparse(item) for item in node.args.defaults]
    return {"name": node.name, "parameters": args, "defaults": defaults, "kwonly": [item.arg for item in node.args.kwonlyargs],
            "vararg": node.args.vararg.arg if node.args.vararg else "", "kwarg": node.args.kwarg.arg if node.args.kwarg else "", "async": isinstance(node, ast.AsyncFunctionDef)}


class PythonInterfaceExtractor:
    def extract_path(self, root: pathlib.Path | str, paths: tuple[str, ...] | None = None) -> dict[str, Any]:
        base = pathlib.Path(root).resolve()
        candidates = [base / path for path in paths] if paths is not None else sorted(base.rglob("*.py"))
        modules = []
        for path in candidates:
            if path.suffix != ".py" or not path.is_file() or "__pycache__" in path.parts:
                continue
            modules.append(self.extract_source(path.read_text(encoding="utf-8"), path.relative_to(base).as_posix()))
        modules.sort(key=lambda item: item["path"])
        body = {"modules": modules}
        return body | {"manifest_hash": canonical_hash(body)}

    def extract_source(self, source: str, relative: str) -> dict[str, Any]:
        try:
            tree = ast.parse(source, filename=relative)
        except SyntaxError as exc:
            raise ValueError(f"syntax error in {relative}:{exc.lineno}") from exc
        functions: list[dict[str, Any]] = []
        classes: list[dict[str, Any]] = []
        imports: list[str] = []
        constants: list[str] = []
        exports: list[str] = []
        cli_options: list[str] = []
        main_guard = False
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                functions.append(_signature(node))
            elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                methods = [_signature(item) for item in node.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("_")]
                classes.append({"name": node.name, "methods": methods})
            elif isinstance(node, ast.Import): imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom): imports.append(node.module or "")
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id.isupper(): constants.append(target.id)
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        value = node.value
                        if isinstance(value, (ast.List, ast.Tuple)):
                            exports.extend(item.value for item in value.elts if isinstance(item, ast.Constant) and isinstance(item.value, str))
            elif isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
                main_guard = "__name__" in ast.unparse(node.test) and "__main__" in ast.unparse(node.test)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
                cli_options.extend(arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("-"))
        module = pathlib.PurePosixPath(relative).with_suffix("").as_posix().replace("/", ".")
        if module.endswith(".__init__"): module = module[:-9]
        return {"path": relative, "module": module, "functions": sorted(functions, key=lambda item: item["name"]),
                "classes": sorted(classes, key=lambda item: item["name"]), "imports": sorted(set(filter(None, imports))),
                "public_constants": sorted(set(constants)), "exports": sorted(set(exports)), "main_guard": main_guard,
                "cli_options": sorted(set(cli_options))}


@dataclass(frozen=True)
class InterfaceCompatibility:
    compatible: bool
    breaking_changes: tuple[str, ...]
    additions: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"compatible": self.compatible, "breaking_changes": list(self.breaking_changes), "additions": list(self.additions)}


def compare_interfaces(old: Mapping[str, Any], new: Mapping[str, Any], *, allow_breaking_change: bool = False) -> InterfaceCompatibility:
    old_modules = {item["module"]: item for item in old.get("modules", [])}
    new_modules = {item["module"]: item for item in new.get("modules", [])}
    breaks: list[str] = []
    additions: list[str] = []
    for module, before in old_modules.items():
        after = new_modules.get(module)
        if after is None:
            breaks.append(f"public module removed:{module}"); continue
        old_funcs = {item["name"]: item for item in before.get("functions", [])}
        new_funcs = {item["name"]: item for item in after.get("functions", [])}
        for name, signature in old_funcs.items():
            if name not in new_funcs: breaks.append(f"public function removed:{module}.{name}")
            elif signature != new_funcs[name]: breaks.append(f"public signature changed:{module}.{name}")
        for option in before.get("cli_options", []):
            if option not in after.get("cli_options", []): breaks.append(f"CLI option removed:{option}")
        if before.get("main_guard") and not after.get("main_guard"): breaks.append(f"entrypoint removed:{module}")
        additions.extend(f"public function added:{module}.{name}" for name in sorted(set(new_funcs) - set(old_funcs)))
    additions.extend(f"public module added:{name}" for name in sorted(set(new_modules) - set(old_modules)))
    return InterfaceCompatibility(not breaks or allow_breaking_change, tuple(breaks), tuple(additions))
