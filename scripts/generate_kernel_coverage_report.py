from __future__ import annotations

import argparse
import hashlib
import json
import pathlib

from kernel_source_identity import ROOT, identity


def _percent(covered: int, total: int) -> float:
    return round(100.0 if total == 0 else covered * 100.0 / total, 2)


def generate(raw_path: pathlib.Path, commit: str, command: str, pytest_exit_code: int) -> dict:
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    source = identity(commit)
    files: dict[str, dict] = {}
    package_totals: dict[str, dict[str, int]] = {}
    for name, item in raw.get("files", {}).items():
        normalized = pathlib.Path(name).as_posix()
        if "/cgkn/" in normalized: normalized = "cgkn/" + normalized.split("/cgkn/", 1)[1]
        if not normalized.startswith("cgkn/"): continue
        summary = item["summary"]
        statements, covered = int(summary["num_statements"]), int(summary["covered_lines"])
        branches, covered_branches = int(summary.get("num_branches", 0)), int(summary.get("covered_branches", 0))
        files[normalized] = {"statements": statements, "covered_statements": covered, "statement_percent": _percent(covered, statements), "branches": branches, "covered_branches": covered_branches, "branch_percent": _percent(covered_branches, branches), "missing_lines": item.get("missing_lines", []), "missing_branches": item.get("missing_branches", [])}
        package = normalized.split("/")[1]
        totals = package_totals.setdefault(package, {"statements": 0, "covered_statements": 0, "branches": 0, "covered_branches": 0})
        for key in totals: totals[key] += files[normalized][key]
    packages = {name: {**totals, "statement_percent": _percent(totals["covered_statements"], totals["statements"]), "branch_percent": _percent(totals["covered_branches"], totals["branches"])} for name, totals in sorted(package_totals.items())}
    layers_doc = json.loads((ROOT / "governance/kernel_layers.json").read_text(encoding="utf-8"))
    layers: dict[str, dict] = {}
    for layer in layers_doc.get("layers", []):
        names = [str(package).split(".")[-1] for package in layer.get("packages", [])]
        selected = [packages[name] for name in names if name in packages]
        totals = {key: sum(int(item[key]) for item in selected) for key in ("statements", "covered_statements", "branches", "covered_branches")}
        layers[layer["id"]] = {**totals, "statement_percent": _percent(totals["covered_statements"], totals["statements"]), "branch_percent": _percent(totals["covered_branches"], totals["branches"])}
    overall = {key: sum(int(item[key]) for item in files.values()) for key in ("statements", "covered_statements", "branches", "covered_branches")}
    overall.update({"statement_percent": _percent(overall["covered_statements"], overall["statements"]), "branch_percent": _percent(overall["covered_branches"], overall["branches"])})
    return {"kind": "CGKNKernelCoverageReport", "schema_version": "2.0", "source_commit": source["source_commit"], "source_tree_sha": source["source_tree_sha"], "core_source_hash": source["core_source_hash"], "command": command, "pytest_result": {"exit_code": pytest_exit_code}, "overall": overall, "files": dict(sorted(files.items())), "packages": packages, "layers": layers, "raw_coverage_hash": "sha256:" + hashlib.sha256(raw_path.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--raw", required=True); parser.add_argument("--source-commit", required=True); parser.add_argument("--command", required=True); parser.add_argument("--pytest-exit-code", required=True, type=int); parser.add_argument("--output", default="governance/kernel_coverage_report.json"); args = parser.parse_args()
    value = generate(ROOT / args.raw, args.source_commit, args.command, args.pytest_exit_code); (ROOT / args.output).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8"); print(json.dumps(value, indent=2)); return 0 if args.pytest_exit_code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
