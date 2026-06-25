#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any


def read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def python_files(project_dir: pathlib.Path) -> list[pathlib.Path]:
    if not project_dir.exists():
        return []
    return [path for path in project_dir.rglob("*.py") if path.is_file()]


def has_terms(path: pathlib.Path, terms: list[str]) -> bool:
    text = read_text(path).lower()
    return any(term in text for term in terms)


def find_named(files: list[pathlib.Path], name: str) -> list[pathlib.Path]:
    return [path for path in files if path.name.lower() == name.lower()]


def check(project_dir: pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    files = python_files(project)
    orchestrators = find_named(files, "orchestrator.py")
    stages = find_named(files, "stages.py")
    cli_entries = [
        path
        for path in files
        if ("cli" in path.name.lower() or path.name.lower() in {"main.py", "__main__.py"})
        and has_terms(path, ["argparse", "click", "typer", "__main__"])
    ]
    gui_entries = [
        path
        for path in files
        if ("gui" in path.name.lower() or "app" in path.name.lower() or "ui" in path.name.lower())
        and has_terms(path, ["tkinter", "streamlit", "gradio", "flask", "fastapi", "pyqt", "pyside"])
    ]
    cli_uses_core = any(has_terms(path, ["orchestrator", "stages"]) for path in cli_entries)
    gui_uses_core = any(has_terms(path, ["orchestrator", "stages"]) for path in gui_entries)
    orchestrator_uses_stages = any(has_terms(path, ["stages", "stage"]) for path in orchestrators)
    blockers: list[str] = []
    if not orchestrators:
        blockers.append("orchestrator.py_missing")
    if not stages:
        blockers.append("stages.py_missing")
    if not cli_entries:
        blockers.append("cli_entry_missing")
    if not gui_entries:
        blockers.append("gui_entry_missing")
    if cli_entries and not cli_uses_core:
        blockers.append("cli_not_using_shared_core")
    if gui_entries and not gui_uses_core:
        blockers.append("gui_not_using_shared_core")
    if orchestrators and not orchestrator_uses_stages:
        blockers.append("orchestrator_not_using_stages")
    return {
        "status": "PASS" if not blockers else "FAIL",
        "blockers": blockers,
        "evidence": {
            "orchestrator": [str(path) for path in orchestrators],
            "stages": [str(path) for path in stages],
            "cli_entries": [str(path) for path in cli_entries],
            "gui_entries": [str(path) for path in gui_entries],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check(pathlib.Path(args.project_dir))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"CGKN_SHARED_GUI_CLI_CORE: {result['status']}")
        for blocker in result["blockers"]:
            print(f"- {blocker}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
