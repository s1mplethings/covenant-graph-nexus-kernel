from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any


PROHIBITED_ROOT_DIRECTORIES = (
    "__pycache__",
    ".pytest_cache",
    ".playwright-mcp",
    ".vs",
)
REQUIRED_IGNORE_RULES = (
    "__pycache__/",
    ".pytest_cache/",
    "/.tmp_*/",
    "artifacts/",
    "generated/",
    "/runs/",
)
REQUIRED_SURFACES = (
    "AGENTS.md",
    "README.md",
    "docs/00_kernel_contract.md",
    "docs/01_contract_registry.md",
    "docs/repository_guide.md",
    "project_management/cgkn/project_management.json",
    "plugins/cgkn/.codex-plugin/plugin.json",
    "tools/cgkn-agent-kit/pyproject.toml",
)


def issue(code: str, path: pathlib.Path, detail: str, root: pathlib.Path) -> dict[str, str]:
    try:
        display = path.resolve().relative_to(root).as_posix()
    except ValueError:
        display = str(path.resolve())
    return {"code": code, "path": display, "detail": detail}


def inspect_repository(root: pathlib.Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    issues: list[dict[str, str]] = []
    if not root.is_dir():
        return {
            "kind": "CGKNRepositoryHygieneReport",
            "schema_version": "1.0",
            "ok": False,
            "root": str(root),
            "issues": [{"code": "ROOT_MISSING", "path": str(root), "detail": "repository root does not exist"}],
        }

    for name in PROHIBITED_ROOT_DIRECTORIES:
        path = root / name
        if path.exists():
            issues.append(issue("ROOT_CACHE_PRESENT", path, "reproducible cache belongs outside the repository handoff", root))

    for path in sorted(root.glob(".tmp_*")):
        if path.exists():
            issues.append(issue("ROOT_TEMP_PRESENT", path, "temporary debug output must be removed or written under the OS temporary directory", root))

    examples = root / "examples"
    if examples.is_dir():
        for config in sorted(examples.rglob("agent-kit.json")):
            if config.parent.name == ".cgkn":
                issues.append(issue("LIVE_SUPPORT_STATE_IN_EXAMPLES", config.parent, "move ad hoc CGKN runs to artifacts or runs", root))

    ignore_path = root / ".gitignore"
    ignore_lines = set()
    if ignore_path.is_file():
        ignore_lines = {
            line.strip()
            for line in ignore_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
    for rule in REQUIRED_IGNORE_RULES:
        if rule not in ignore_lines:
            issues.append(issue("IGNORE_BOUNDARY_MISSING", ignore_path, f"missing ignore rule: {rule}", root))

    for relative in REQUIRED_SURFACES:
        path = root / relative
        if not path.is_file():
            issues.append(issue("NAVIGATION_SURFACE_MISSING", path, "required repository surface is missing", root))

    return {
        "kind": "CGKNRepositoryHygieneReport",
        "schema_version": "1.0",
        "ok": not issues,
        "root": str(root),
        "checks": {
            "prohibited_root_directories": list(PROHIBITED_ROOT_DIRECTORIES),
            "required_ignore_rules": list(REQUIRED_IGNORE_RULES),
            "required_surfaces": list(REQUIRED_SURFACES),
        },
        "issues": issues,
        "note": "This read-only support report is not formal delivery evidence.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect CGKN repository navigation and local hygiene without deleting files.")
    parser.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = inspect_repository(pathlib.Path(args.root))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif report["ok"]:
        print("Repository hygiene: clean")
    else:
        print(f"Repository hygiene: {len(report['issues'])} issue(s)")
        for item in report["issues"]:
            print(f"- {item['code']}: {item['path']}: {item['detail']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
