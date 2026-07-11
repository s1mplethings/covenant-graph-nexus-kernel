from __future__ import annotations

import pathlib
import re
import tempfile
import zipfile
from typing import Any


ENTRYPOINT_NAMES = {"index.html", "app.py", "main.py", "server.js", "package.json"}
DEPENDENCY_NAMES = {"package.json", "requirements.txt", "pyproject.toml"}
DOC_ONLY_SUFFIXES = {".md", ".rst", ".txt", ".json", ".jsonl", ".log", ".yaml", ".yml", ".toml", ".ini"}


def _copy_zip_to_temp(bundle: pathlib.Path) -> pathlib.Path:
    root = pathlib.Path(tempfile.mkdtemp(prefix="cgnk_runnable_contract_"))
    with zipfile.ZipFile(bundle) as zf:
        zf.extractall(root)
    return root


def _root(path: pathlib.Path) -> tuple[pathlib.Path, tempfile.TemporaryDirectory[str] | None]:
    resolved = pathlib.Path(path)
    if resolved.is_file() and resolved.suffix.lower() == ".zip":
        temp = tempfile.TemporaryDirectory(prefix="cgnk_runnable_contract_")
        root = pathlib.Path(temp.name)
        with zipfile.ZipFile(resolved) as zf:
            zf.extractall(root)
        return root, temp
    return resolved, None


def _rel(root: pathlib.Path, path: pathlib.Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except Exception:
        return str(path)


def _readme_startup_commands(readme: pathlib.Path) -> list[str]:
    if not readme.exists():
        return []
    text = readme.read_text(encoding="utf-8", errors="replace")
    commands: list[str] = []
    for line in text.splitlines():
        stripped = line.strip().strip("`")
        if re.search(r"\b(python|uvicorn|flask|streamlit|npm|pnpm|yarn|node)\b", stripped, flags=re.I):
            commands.append(stripped.lstrip("-* ").strip())
    return commands[:10]


def evaluate_project(path: str | pathlib.Path) -> dict[str, Any]:
    root, temp = _root(pathlib.Path(path))
    try:
        missing: list[str] = []
        files = [item for item in root.rglob("*") if item.is_file()] if root.exists() else []
        readmes = [item for item in files if item.name.lower() == "readme.md"]
        entrypoints = [
            _rel(root, item)
            for item in files
            if item.name in ENTRYPOINT_NAMES or (item.match("src/App.*") and item.suffix.lower() in {".js", ".jsx", ".ts", ".tsx"})
        ]
        dependency_files = [_rel(root, item) for item in files if item.name in DEPENDENCY_NAMES]
        test_files = [_rel(root, item) for item in files if "test" in item.name.lower() or "tests" in item.parts]
        startup_commands: list[str] = []
        for readme in readmes:
            startup_commands.extend(_readme_startup_commands(readme))
        user_files = [item for item in files if item.name not in {"delivery_manifest.json", "packager_run_log.txt", "final_project_bundle.zip"}]
        docs_only = bool(user_files) and all(item.suffix.lower() in DOC_ONLY_SUFFIXES for item in user_files)

        if not root.exists() or not files:
            missing.append("project_root")
        if not readmes:
            missing.append("README.md")
        if readmes and not startup_commands:
            missing.append("README_startup_command")
        if not dependency_files:
            missing.append("dependency_file")
        if not entrypoints:
            missing.append("entrypoint")
        if not test_files and not startup_commands:
            missing.append("test_or_smoke_entry")
        if docs_only:
            missing.append("not_docs_only")

        return {
            "runnable_project": not missing,
            "entrypoints": entrypoints,
            "startup_commands": startup_commands,
            "dependency_files": dependency_files,
            "test_commands": startup_commands,
            "missing": missing,
            "verdict": "PASS" if not missing else "FAIL",
        }
    finally:
        if temp is not None:
            temp.cleanup()
