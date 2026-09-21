from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
from collections import defaultdict
from typing import Any


PROHIBITED_ROOT_DIRECTORIES = ("__pycache__", ".pytest_cache", ".playwright-mcp", ".vs")
REQUIRED_IGNORE_RULES = (
    "__pycache__/",
    ".pytest_cache/",
    "/.tmp_*/",
    "/artifacts/",
    "/generated/",
    "/runs/",
    "/.cgkn/",
    "/workspaces/",
)
REQUIRED_SURFACES = (
    "AGENTS.md",
    "README.md",
    "docs/00_kernel_contract.md",
    "docs/01_contract_registry.md",
    "docs/repository_guide.md",
    "specs/README.md",
    "specs/artifacts",
    "specs/modules",
    "specs/flows",
    "specs/policies",
    "evidence/artifact-kernel/v0.3/verification_summary.json",
    "project_management/current/PROJECT_MANAGEMENT.md",
    "project_management/current/active_iteration.json",
    "project_management/summaries/v0.3.md",
    "plugins/cgkn/.codex-plugin/plugin.json",
    "tools/cgkn-agent-kit/pyproject.toml",
)
TRACKED_RUNTIME_PREFIXES = (
    "runs/",
    "generated/",
    "artifacts/",
    "provider_outputs/",
    "coverage/",
    "raw_logs/",
    "raw_screenshots/",
    ".cgkn/",
    "workspaces/",
)
EXAMPLE_RUNTIME_PREFIXES = (
    "examples/project_memory/",
    "examples/local_studio/",
    "examples/runtime_runs/",
    "examples/product_studio/runs/",
    "examples/generated_projects/",
)
EXAMPLE_RUNTIME_NAMES = {
    "artifact_index.json",
    "run_manifest.json",
    "feed_forward_report.json",
    "generation_checkpoint.json",
    "provider_output.json",
}
SIZE_WARNING_BYTES = 2 * 1024 * 1024
SIZE_FAILURE_BYTES = 10 * 1024 * 1024
BUNDLE_WARNING_BYTES = 5 * 1024 * 1024
OVERSIZE_ALLOWLIST: set[str] = set()


def issue(code: str, path: pathlib.Path | str, detail: str, root: pathlib.Path) -> dict[str, str]:
    candidate = pathlib.Path(path)
    try:
        display = candidate.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        display = candidate.as_posix()
    return {"code": code, "path": display, "detail": detail}


def tracked_files(root: pathlib.Path) -> dict[str, int]:
    completed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        return {}
    result: dict[str, int] = {}
    for relative in completed.stdout.split("\0"):
        if not relative:
            continue
        path = root / relative
        if path.is_file():
            result[relative.replace("\\", "/")] = path.stat().st_size
    return result


def inspect_tracked_paths(files: dict[str, int], root: pathlib.Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    evidence_bundles: dict[str, int] = defaultdict(int)
    example_bundles: dict[str, int] = defaultdict(int)
    for relative, size in sorted(files.items()):
        if relative.startswith(TRACKED_RUNTIME_PREFIXES):
            issues.append(issue("TRACKED_RUNTIME_OUTPUT", relative, "raw runtime data must not be tracked", root))
        if relative.startswith(EXAMPLE_RUNTIME_PREFIXES) or (
            relative.startswith("examples/") and pathlib.PurePosixPath(relative).name in EXAMPLE_RUNTIME_NAMES
        ):
            issues.append(issue("RUNTIME_DATA_UNDER_EXAMPLES", relative, "examples must contain only readable reproducible inputs and expected summaries", root))
        if relative not in OVERSIZE_ALLOWLIST and size > SIZE_FAILURE_BYTES:
            issues.append(issue("TRACKED_FILE_TOO_LARGE", relative, f"tracked file is {size} bytes; limit is {SIZE_FAILURE_BYTES}", root))
        elif size > SIZE_WARNING_BYTES:
            warnings.append(issue("TRACKED_FILE_LARGE", relative, f"tracked file is {size} bytes; review threshold is {SIZE_WARNING_BYTES}", root))
        parts = relative.split("/")
        if relative.startswith("evidence/"):
            evidence_bundles["/".join(parts[:3])] += size
        if relative.startswith("examples/"):
            example_bundles["/".join(parts[:3])] += size
    for bundle, size in sorted(evidence_bundles.items()):
        if size > BUNDLE_WARNING_BYTES:
            warnings.append(issue("EVIDENCE_BUNDLE_LARGE", bundle, f"evidence bundle is {size} bytes; review threshold is {BUNDLE_WARNING_BYTES}", root))
    for bundle, size in sorted(example_bundles.items()):
        if size > BUNDLE_WARNING_BYTES:
            warnings.append(issue("EXAMPLE_BUNDLE_LARGE", bundle, f"example bundle is {size} bytes; review threshold is {BUNDLE_WARNING_BYTES}", root))
    return issues, warnings


def inspect_repository(root: pathlib.Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if not root.is_dir():
        return {
            "kind": "CGKNRepositoryHygieneReport",
            "schema_version": "2.0",
            "ok": False,
            "root": str(root),
            "issues": [{"code": "ROOT_MISSING", "path": str(root), "detail": "repository root does not exist"}],
            "warnings": [],
        }

    for name in PROHIBITED_ROOT_DIRECTORIES:
        path = root / name
        if path.exists():
            warnings.append(issue("ROOT_CACHE_PRESENT", path, "ignored reproducible cache is present locally; it is not part of the Git handoff", root))
    for path in sorted(root.glob(".tmp_*")):
        if path.exists():
            issues.append(issue("ROOT_TEMP_PRESENT", path, "temporary debug output belongs in the OS temporary directory", root))

    ignore_path = root / ".gitignore"
    ignore_lines: set[str] = set()
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
        if not path.exists():
            issues.append(issue("NAVIGATION_SURFACE_MISSING", path, "required repository surface is missing", root))

    tracked = tracked_files(root)
    tracked_issues, tracked_warnings = inspect_tracked_paths(tracked, root)
    issues.extend(tracked_issues)
    warnings.extend(tracked_warnings)
    return {
        "kind": "CGKNRepositoryHygieneReport",
        "schema_version": "2.0",
        "ok": not issues,
        "root": str(root),
        "checks": {
            "trackedFiles": len(tracked),
            "trackedRuntimePrefixes": list(TRACKED_RUNTIME_PREFIXES),
            "exampleRuntimePrefixes": list(EXAMPLE_RUNTIME_PREFIXES),
            "sizeWarningBytes": SIZE_WARNING_BYTES,
            "sizeFailureBytes": SIZE_FAILURE_BYTES,
            "bundleWarningBytes": BUNDLE_WARNING_BYTES,
            "requiredIgnoreRules": list(REQUIRED_IGNORE_RULES),
            "requiredSurfaces": list(REQUIRED_SURFACES),
        },
        "issues": issues,
        "warnings": warnings,
        "note": "This read-only support report is not formal delivery evidence.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect CGKN repository layout and retention boundaries without deleting files.")
    parser.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = inspect_repository(pathlib.Path(args.root))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif report["ok"]:
        print(f"Repository hygiene: clean ({len(report['warnings'])} warning(s))")
        for item in report["warnings"]:
            print(f"- WARNING {item['code']}: {item['path']}: {item['detail']}")
    else:
        print(f"Repository hygiene: {len(report['issues'])} issue(s), {len(report['warnings'])} warning(s)")
        for item in report["issues"]:
            print(f"- {item['code']}: {item['path']}: {item['detail']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
