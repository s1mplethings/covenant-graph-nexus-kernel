#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
from collections import defaultdict
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORT_DIR = pathlib.Path("evidence/repository-layout-v1")

DIRECTORY_MOVES = (
    ("examples/artifacts", "specs/artifacts"),
    ("examples/modules", "specs/modules"),
    ("examples/flows", "specs/flows"),
    ("examples/policies", "specs/policies"),
    ("examples/migrations", "specs/migrations"),
    ("examples/compile_results", "tests/fixtures/compile_results"),
    ("examples/proposals", "tests/fixtures/proposals"),
    ("examples/boundary", "examples/minimal/boundary"),
    ("examples/knowledge", "examples/project-generation/knowledge"),
    ("examples/artifact_driven_demo", "examples/artifact-driven/todo-refactor"),
)
FILE_MOVES = tuple(
    (f"examples/agent_context.{name}.contract_pack.json", f"specs/context_packs/agent_context.{name}.contract_pack.json")
    for name in (
        "local_pipeline_composition",
        "local_pipeline_execution",
        "modular_project_generation",
        "project_generation",
        "project_refactor",
    )
)
UNTRACK_PATHS = (
    "artifacts",
    "examples/project_memory",
    "examples/local_studio",
    "examples/product_studio",
    "examples/artifact-driven/todo-refactor/incremental_recompute_evidence.json",
    "examples/artifact-driven/todo-refactor/sample_run.json",
    "project_management/cgkn",
    "project_management/ENTERPRISE_EXPERIENCE.md",
    "project_management/enterprise_experience.json",
)
REFERENCE_PATTERNS = {
    "python_import": re.compile(r"(?:from|import)\s+([A-Za-z_][\w.]*)"),
    "schema_ref": re.compile(r'"schema_ref"\s*:\s*"([^"]+)"'),
    "flow_ref": re.compile(r"flow\.[A-Za-z0-9_.-]+@\d+"),
    "module_ref": re.compile(r"module\.[A-Za-z0-9_.-]+@\d+"),
    "policy_ref": re.compile(r"policy\.[A-Za-z0-9_.-]+@\d+"),
    "legacy_spec_path": re.compile(r"examples[/\\](?:artifacts|modules|flows|policies|migrations)(?:[/\\][^\s\"'`]+)?"),
    "markdown_link": re.compile(r"\[[^\]]+\]\(([^)]+)\)"),
}
TEXT_SUFFIXES = {".py", ".json", ".md", ".toml", ".yaml", ".yml", ".txt", ".ps1", ".sh", ".bat"}


def run_git(root: pathlib.Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    return completed.stdout.strip()


def head_entries(root: pathlib.Path, revision: str = "HEAD") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    raw = run_git(root, "ls-tree", "-r", "-l", revision)
    pattern = re.compile(r"^\d+\s+\w+\s+[0-9a-f]+\s+(\d+)\t(.+)$")
    for line in raw.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        path = match.group(2)
        rows.append({"path": path, "bytes": int(match.group(1)), "topLevel": path.split("/", 1)[0]})
    return rows


def index_entries(root: pathlib.Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path_text in run_git(root, "ls-files").splitlines():
        path = root / path_text
        if path.is_file():
            rows.append({"path": path_text, "bytes": path.stat().st_size, "topLevel": path_text.split("/", 1)[0]})
    return rows


def metrics(rows: list[dict[str, Any]], revision: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["topLevel"]].append(row)
    directories = [
        {"path": name, "files": len(items), "bytes": sum(item["bytes"] for item in items)}
        for name, items in groups.items()
    ]
    directories.sort(key=lambda item: (-item["bytes"], item["path"]))
    largest = sorted(rows, key=lambda item: (-item["bytes"], item["path"]))[:50]
    runtime_prefixes = ("artifacts/", "runs/", "generated/", "provider_outputs/", "coverage/", "raw_logs/", "raw_screenshots/")
    return {
        "kind": "CGKNRepositoryMetrics",
        "schemaVersion": "1",
        "revision": revision,
        "trackedFiles": len(rows),
        "trackedBytes": sum(row["bytes"] for row in rows),
        "trackedRuntimeFiles": sum(row["path"].startswith(runtime_prefixes) for row in rows),
        "topLevelDirectories": directories,
        "largestFiles": largest,
        "focus": {
            name: {
                "files": sum(row["path"] == name or row["path"].startswith(name + "/") for row in rows),
                "bytes": sum(row["bytes"] for row in rows if row["path"] == name or row["path"].startswith(name + "/")),
            }
            for name in ("artifacts", "examples", "project_management", "runs", "generated", "tests", "scripts", "schemas", "contracts", "cgkn", "docs", "benchmarks", "specs", "evidence")
        },
    }


def inventory(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        parts = row["path"].split("/")
        key = "/".join(parts[:2]) if len(parts) > 1 else parts[0]
        groups[key].append(row)
    return {
        "kind": "CGKNRepositoryLayoutInventory",
        "schemaVersion": "1",
        "areas": [
            {"path": name, "files": len(items), "bytes": sum(item["bytes"] for item in items)}
            for name, items in sorted(groups.items(), key=lambda item: (-sum(row["bytes"] for row in item[1]), item[0]))
        ],
        "classification": {
            "source": ["cgkn", "scripts", "tools", "plugins", "skills", "legacy", "src"],
            "spec": ["contracts", "schemas", "examples/artifacts", "examples/modules", "examples/flows", "examples/policies"],
            "example": ["examples/artifact_driven_demo", "examples/knowledge", "examples/boundary"],
            "evidence": ["project_management/cgkn/iterations", "artifacts"],
            "runtime": ["artifacts", "examples/project_memory", "examples/local_studio", "examples/product_studio/runs"],
        },
    }


def reference_graph(root: pathlib.Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    references: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        relative = row["path"]
        path = root / relative
        if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file() or row["bytes"] > 2_000_000:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, start=1):
            for relation, pattern in REFERENCE_PATTERNS.items():
                for match in pattern.finditer(line):
                    target = match.group(1) if match.groups() else match.group(0)
                    references[relative][relation].add(target)
    sources = [
        {
            "source": source,
            "references": {relation: sorted(targets) for relation, targets in sorted(relations.items())},
        }
        for source, relations in sorted(references.items())
    ]
    relation_counts: dict[str, int] = defaultdict(int)
    for row in sources:
        for relation, targets in row["references"].items():
            relation_counts[relation] += len(targets)
    return {
        "kind": "CGKNRepositoryReferenceGraph",
        "schemaVersion": "1",
        "sources": sources,
        "summary": {
            "trackedNodesScanned": len(rows),
            "sourcesWithReferences": len(sources),
            "uniqueReferences": sum(relation_counts.values()),
            "relationCounts": dict(sorted(relation_counts.items())),
            "legacySpecPathReferences": relation_counts.get("legacy_spec_path", 0),
        },
    }


def cleanup_plan(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tracked = {row["path"] for row in rows}
    untrack = [path for path in UNTRACK_PATHS if any(item == path or item.startswith(path.rstrip("/") + "/") for item in tracked) or path.startswith("examples/artifact-driven/")]
    untracked_files = sum(any(row["path"] == path or row["path"].startswith(path.rstrip("/") + "/") for path in UNTRACK_PATHS[:4]) for row in rows)
    untracked_bytes = sum(row["bytes"] for row in rows if any(row["path"] == path or row["path"].startswith(path.rstrip("/") + "/") for path in UNTRACK_PATHS[:4]))
    return {
        "kind": "CGKNRepositoryCleanupPlan",
        "schemaVersion": "1",
        "moves": [{"from": source, "to": target} for source, target in DIRECTORY_MOVES + FILE_MOVES],
        "untrack": untrack,
        "delete": [],
        "promoteToEvidence": [
            {"source": "runs/<run-id>", "target": "evidence/<category>/<version>", "method": "scripts/promote_evidence.py"},
            {"source": "artifacts historical claims", "target": "evidence/artifact-kernel/v0.3", "method": "curated summary only"},
        ],
        "keep": ["cgkn", "contracts", "schemas", "scripts", "tests", "benchmarks", "docs", "plugins", "skills", "tools", "legacy"],
        "referenceUpdates": [
            {"from": "examples/<registry>", "to": "specs/<registry>", "scope": "loaders, policies, tests, docs, CLI"},
            {"from": "project_management/cgkn", "to": "project_management/current and project_management/summaries", "scope": "governance docs and tests"},
        ],
        "compatibilityChanges": ["specs-first loader with deprecated examples fallback and warning"],
        "estimatedFileReduction": untracked_files,
        "estimatedSizeReductionBytes": untracked_bytes,
        "brokenReferenceRisk": "high until referenceUpdates are complete; validation is mandatory before commit",
    }


def branch_report(root: pathlib.Path) -> dict[str, Any]:
    main_sha = run_git(root, "rev-parse", "main")
    branch_sha = run_git(root, "rev-parse", "HEAD")
    counts = run_git(root, "rev-list", "--left-right", "--count", f"main...{branch_sha}").split()
    changed = run_git(root, "diff", "--name-only", f"main...{branch_sha}").splitlines()
    groups = sorted({path.split("/", 1)[0] for path in changed if path})
    return {
        "kind": "CGKNBranchReconciliationReport",
        "schemaVersion": "1",
        "mainSha": main_sha,
        "branchSha": branch_sha,
        "branch": run_git(root, "branch", "--show-current"),
        "ahead": int(counts[1]),
        "behind": int(counts[0]),
        "majorFeatureGroups": groups,
        "mergeRisks": [
            "main and the Artifact-driven development branch contain broad independent changes",
            "directory moves can conflict with changes that still target examples registries",
            "Provider and delivery mainline must be protected during reconciliation",
        ],
        "recommendedMergeStrategy": "review and merge the cleanup branch into the Artifact-driven branch first; reconcile that reviewed tip with main using a non-force merge or PR, never history rewriting",
    }


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def audit(root: pathlib.Path, output: pathlib.Path) -> None:
    rows = head_entries(root)
    write_json(output / "repository_metrics_before.json", metrics(rows, "HEAD-before-cleanup"))
    write_json(output / "repository_layout_inventory.json", inventory(rows))
    write_json(output / "repository_reference_graph.json", reference_graph(root, rows))
    write_json(output / "repository_cleanup_plan.json", cleanup_plan(rows))
    write_json(output / "branch_reconciliation_report.json", branch_report(root))


def dry_run(root: pathlib.Path) -> int:
    plan = cleanup_plan(head_entries(root))
    print(json.dumps({
        "mode": "dry-run",
        "move": plan["moves"],
        "untrack": plan["untrack"],
        "keep": plan["keep"],
        "promote": plan["promoteToEvidence"],
        "delete": plan["delete"],
        "brokenReferenceRisk": plan["brokenReferenceRisk"],
        "estimatedFileReduction": plan["estimatedFileReduction"],
        "estimatedSizeReductionBytes": plan["estimatedSizeReductionBytes"],
    }, ensure_ascii=False, indent=2))
    return 0


def apply(root: pathlib.Path) -> int:
    if run_git(root, "branch", "--show-current") != "codex/repository-layout-v1":
        raise SystemExit("cleanup apply is restricted to codex/repository-layout-v1")
    for source, target in DIRECTORY_MOVES + FILE_MOVES:
        if not (root / source).exists():
            continue
        (root / target).parent.mkdir(parents=True, exist_ok=True)
        run_git(root, "mv", source, target)
    for path in UNTRACK_PATHS:
        run_git(root, "rm", "-r", "--cached", "--ignore-unmatch", path)
    print(json.dumps({"mode": "apply", "movesApplied": len(DIRECTORY_MOVES + FILE_MOVES), "untrackRequests": len(UNTRACK_PATHS), "localFilesDeleted": 0}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit and apply the CGKN Repository Layout v1 cleanup.")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--audit", action="store_true", help="write before metrics, inventory, reference graph, plan, and branch report")
    modes.add_argument("--dry-run", action="store_true", help="print the cleanup actions without modifying files or the index")
    modes.add_argument("--apply", action="store_true", help="apply moves and untrack runtime data without deleting local files")
    modes.add_argument("--metrics-after", action="store_true", help="write metrics for the current Git index")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--output-dir", default=str(REPORT_DIR))
    args = parser.parse_args(argv)
    root = pathlib.Path(args.root).resolve()
    output = (root / args.output_dir).resolve()
    if args.audit:
        audit(root, output)
        return 0
    if args.dry_run:
        return dry_run(root)
    if args.apply:
        return apply(root)
    write_json(output / "repository_metrics_after.json", metrics(index_entries(root), "Git-index-after-cleanup"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
