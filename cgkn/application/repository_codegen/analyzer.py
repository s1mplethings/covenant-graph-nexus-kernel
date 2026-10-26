from __future__ import annotations

import ast
import hashlib
import pathlib
from collections import Counter
from .contracts import ChangeContract, ChangeRequest, ImpactSet, RepositorySnapshot


PROTECTED = (".git", ".github", ".cgkn", ".pytest_cache", "governance", "artifacts")


def _safe_files(root: pathlib.Path) -> list[pathlib.Path]:
    return [path for path in sorted(root.rglob("*")) if path.is_file() and not any(part in PROTECTED or part == "__pycache__" for part in path.relative_to(root).parts)]


def snapshot_repository(root: pathlib.Path | str, repository_id: str = "repository") -> RepositorySnapshot:
    base = pathlib.Path(root).resolve(); rows = {}; languages = Counter(); interfaces = {}; graph = {}; entrypoints = []; tests = set(); deps = []
    for path in _safe_files(base):
        relative = path.relative_to(base).as_posix(); data = path.read_bytes(); rows[relative] = "sha256:" + hashlib.sha256(data).hexdigest(); languages[path.suffix or "<none>"] += 1
        if relative in {"pyproject.toml", "requirements.txt"}: deps.append(relative)
        if path.suffix == ".py":
            try: tree = ast.parse(data.decode("utf-8"))
            except (SyntaxError, UnicodeDecodeError): continue
            names = tuple(sorted(node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_")))
            interfaces[relative] = names
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import): imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module: imports.append(node.module)
            graph[relative] = tuple(sorted(set(imports)))
            if relative.endswith("__main__.py") or any(isinstance(node, ast.If) and isinstance(node.test, ast.Compare) for node in tree.body): entrypoints.append(relative)
            if relative.startswith("tests/") or path.name.startswith("test_"): tests.add(relative.split("/", 1)[0] if "/" in relative else relative)
    identity = "\n".join(f"{key}:{value}" for key, value in sorted(rows.items()))
    return RepositorySnapshot(repository_id, "sha256:" + hashlib.sha256(identity.encode()).hexdigest(), rows, dict(languages), tuple(entrypoints), tuple(sorted(tests)), interfaces, tuple(deps), graph, PROTECTED)


def analyze_impact(snapshot: RepositorySnapshot, request: ChangeRequest) -> ImpactSet:
    hinted = tuple(dict.fromkeys(pathlib.PurePosixPath(item).as_posix() for item in request.scope_hint))
    affected_tests = tuple(path for path in snapshot.files if path.startswith("tests/") and any(pathlib.PurePosixPath(module).stem in path for module in hinted))
    return ImpactSet(hinted, affected_tests, {path: ("scope_hint",) for path in hinted})


def compile_change_contract(snapshot: RepositorySnapshot, request: ChangeRequest) -> ChangeContract:
    impact = analyze_impact(snapshot, request)
    if not impact.affected_modules or len(impact.affected_modules) > 2:
        raise ValueError("change contract requires one or two deterministic affected modules")
    if any(path.startswith(snapshot.protected_paths) for path in impact.affected_modules):
        raise ValueError("change scope intersects protected paths")
    required = {path: snapshot.public_interfaces.get(path, ()) for path in impact.affected_modules}
    read_paths = tuple(dict.fromkeys((*impact.affected_modules, *impact.affected_tests)))
    return ChangeContract(request.change_id, impact.affected_modules, impact.affected_modules, read_paths, required, required, snapshot.protected_paths, request.requirements, request.acceptance, "no new external dependencies", "MEDIUM")

