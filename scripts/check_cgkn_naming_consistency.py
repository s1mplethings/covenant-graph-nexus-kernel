#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import pathlib
from dataclasses import dataclass


ROOT = pathlib.Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "artifacts" / "cgnk_naming_consistency_report.md"

# Legacy machine identifiers may remain in frozen schemas, Python paths, and
# historical evidence, but they are not the current public project name.
LEGACY_COMPATIBILITY_TERMS = ["CGKN", "CTCP", "ACFV"]  # legacy compatibility tokens

STRICT_PATTERNS = [
    "README.md",
    "AGENTS.md",
    "PRODUCT_GOAL.md",
    "MVP_SCOPE.md",
    "CHANGELOG.md",
    "CITATION.cff",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/ARCHITECTURE.md",
    "docs/BENCHMARKS.md",
    "docs/RELEASE_NOTES.md",
    "docs/REPRODUCIBILITY.md",
    "docs/THIRD_PARTY_LICENSES.md",
    "research/release-056/README.md",
    "research/release-056/RELEASE_CLAIM_LEDGER.json",
    "research/release-056/research_summary.json",
    "research/release-056/report/references.bib",
    "research/release-056/report/reproduction.md",
    "research/release-056/report/success_rate.svg",
    "research/release-056/report/technical_report.md",
    "project_management/summaries/ITER-056_FINAL_REPORT.md",
    "docs/requirement_decision_first.md",
    "docs/requirement_decision_lane.md",
    "docs/continuous_verified_generation_loop.md",
    "docs/agent_test_integrated_behavior.md",
    "docs/customer_agent_long_journey_trial.md",
    "docs/release_candidate_acceptance.md",
    "artifacts/release_candidate_*.md",
    "artifacts/release_candidate_*.json",
    "artifacts/continuous_generation_*.md",
    "artifacts/continuous_generation_iterations.jsonl",
    "artifacts/cgnk_naming_consistency_report.md",
    "artifacts/stale_test_update_report.md",
    "artifacts/requirement_decision_benchmark_summary.md",
    "artifacts/requirement_decision_benchmark.json",
    "artifacts/requirement_decision_benchmark_runs/**",
    "scripts/check_cgkn_naming_consistency.py",
    "scripts/continuous_generation_ledger.py",
    "scripts/run_continuous_verified_generation.py",
    "scripts/requirement_decision_lane.py",
    "scripts/run_requirement_decision_benchmark.py",
    "scripts/shared_gui_cli_core_checker.py",
    "scripts/stage_artifact_schema_checker.py",
    "tests/test_cgkn_naming_consistency.py",
    "tests/test_continuous_verified_generation.py",
    "tests/test_agent_test_integrated_behavior.py",
    "tests/test_contract_driven_materialization.py",
    "tests/test_shared_gui_cli_core_checker.py",
    "tests/test_stage_artifact_schema_checker.py",
]

SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", ".mypy_cache", "node_modules"}


@dataclass
class NamingFinding:
    path: str
    line: int
    context: str


def rel(path: pathlib.Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def is_text_file(path: pathlib.Path) -> bool:
    if not path.is_file():
        return False
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".zip", ".pyc", ".mp4", ".webm"}:
        return False
    try:
        path.read_text(encoding="utf-8", errors="replace")
        return True
    except Exception:
        return False


def strict_files(root: pathlib.Path = ROOT) -> list[pathlib.Path]:
    files: dict[str, pathlib.Path] = {}
    for pattern in STRICT_PATTERNS:
        if "**" in pattern or "*" in pattern:
            for path in root.glob(pattern):
                if is_text_file(path):
                    files[rel(path)] = path
        else:
            path = root / pattern
            if is_text_file(path):
                files[rel(path)] = path
    return [files[key] for key in sorted(files)]


def line_is_legacy_context(line: str) -> bool:
    lowered = line.lower()
    return (
        "legacy compatibility" in lowered
        or "historical compatibility" in lowered
        or "legacy machine identifier" in lowered
        or "legacy_machine_identifier" in lowered
        or '"kind": "cgkn' in lowered
        or "cgkn_" in lowered
    )


def scan_file(path: pathlib.Path) -> list[NamingFinding]:
    findings: list[NamingFinding] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for index, line in enumerate(text.splitlines(), 1):
        if line_is_legacy_context(line):
            continue
        if any(term in line for term in LEGACY_COMPATIBILITY_TERMS):
            findings.append(NamingFinding(path=rel(path), line=index, context="legacy token outside compatibility context"))
    return findings


def scan() -> dict[str, object]:
    files = strict_files()
    findings: list[NamingFinding] = []
    for path in files:
        findings.extend(scan_file(path))
    return {
        "status": "PASS" if not findings else "FAIL",
        "files_scanned": [rel(path) for path in files],
        "findings": [finding.__dict__ for finding in findings],
    }


def write_report(result: dict[str, object], report_path: pathlib.Path = REPORT_PATH) -> None:
    findings = result.get("findings", [])
    files = result.get("files_scanned", [])
    lines = [
        "# CGNK Naming Consistency Report",
        "",
        f"- status: `{result.get('status')}`",
        f"- strict files scanned: `{len(files) if isinstance(files, list) else 0}`",
        "- formal project name: `CGNK` (Covenant Graph Nexus Kernel)",
        "- rule: current public docs, reports, benchmarks, prompts, and artifacts use CGNK as the public project name.",
        "- legacy machine identifier: `CGKN` may remain only in frozen schemas, package/API compatibility surfaces, and explicitly historical evidence.",
        "",
    ]
    if findings:
        lines.append("## Findings")
        for item in findings if isinstance(findings, list) else []:
            if not isinstance(item, dict):
                continue
            lines.append(f"- `{item.get('path')}` line `{item.get('line')}`: legacy token outside compatibility context")
    else:
        lines.append("No strict-scope naming violations found.")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=str(REPORT_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = scan()
    write_report(result, pathlib.Path(args.report))
    if args.json:
        import json

        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"CGNK_NAMING_CONSISTENCY: {result['status']}")
        print(f"report: {args.report}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
