#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import continuous_generation_ledger


CLASSIFICATION_JSON = ARTIFACTS / "release_candidate_file_classification.json"
CLASSIFICATION_MD = ARTIFACTS / "release_candidate_file_classification.md"
ACCEPTANCE_JSON = ARTIFACTS / "release_candidate_acceptance.json"
SUMMARY_MD = ARTIFACTS / "release_candidate_summary.md"
KNOWN_GAPS_MD = ARTIFACTS / "release_candidate_known_gaps.md"
COMMIT_PLAN_MD = ARTIFACTS / "release_candidate_commit_plan.md"

RECOMMENDED_COMMIT_FILES = {
    "README.md",
    "AGENTS.md",
    "docs/customer_agent_long_journey_trial.md",
    "docs/release_candidate_acceptance.md",
    "scripts/check_cgkn_naming_consistency.py",
    "scripts/customer_agent_scorecard.py",
    "scripts/customer_agent_simulator.py",
    "scripts/run_customer_agent_long_journey_trial.py",
    "scripts/release_candidate_gate.py",
    "tests/test_customer_agent_long_journey_trial.py",
    "tests/test_release_candidate_gate.py",
    "artifacts/customer_agent_dialogue.jsonl",
    "artifacts/customer_agent_gap_report.md",
    "artifacts/customer_agent_long_journey_summary.md",
    "artifacts/customer_agent_long_journey_trial.json",
    "artifacts/customer_agent_rework_report.md",
    "artifacts/customer_agent_scorecard.json",
    "artifacts/release_candidate_acceptance.json",
    "artifacts/release_candidate_summary.md",
    "artifacts/release_candidate_known_gaps.md",
    "artifacts/release_candidate_file_classification.json",
    "artifacts/release_candidate_file_classification.md",
    "artifacts/release_candidate_commit_plan.md",
    "artifacts/full_pytest_result.json",
    "artifacts/pr_3_changed_files.txt",
    "artifacts/pr_3_scope_audit.json",
    "artifacts/pr_3_scope_audit.md",
    "artifacts/cgkn_naming_consistency_report.md",
    "artifacts/continuous_generation_current_gaps.md",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def read_text(path: pathlib.Path, limit: int = 100000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def git_lines(args: list[str], root: pathlib.Path = ROOT) -> list[str]:
    try:
        proc = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, timeout=30)
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def git_status_porcelain(root: pathlib.Path = ROOT) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in git_lines(["status", "--short"], root):
        status = line[:2].strip() or "M"
        path = line[3:] if len(line) > 3 else line.strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        rows.append({"status": status, "path": path.replace("\\", "/")})
    return rows


def classify_path(path: str) -> str:
    p = path.replace("\\", "/")
    if p in {"README.md", "AGENTS.md"} or p.startswith("docs/"):
        return "C_docs"
    if p.startswith("tests/"):
        return "B_test_code"
    if p.startswith("scripts/") or p.endswith(".py"):
        return "A_core_code"
    if p.startswith("examples/project_memory/"):
        return "F_examples_project_memory_or_historical_dirty"
    if p.startswith("examples/local_studio/") or p.startswith("examples/runtime_runs/") or p.startswith("generated/"):
        return "E_runtime_generated_artifacts"
    if p.startswith("artifacts/customer_agent_long_journey_runs/"):
        return "E_runtime_generated_artifacts"
    if p in {"artifacts/pr_3_changed_files.txt", "artifacts/pr_3_scope_audit.json", "artifacts/pr_3_scope_audit.md"}:
        return "D_necessary_artifacts"
    if p.startswith("artifacts/customer_agent_") or p.startswith("artifacts/release_candidate_"):
        return "D_necessary_artifacts"
    if p == "artifacts/full_pytest_result.json":
        return "D_necessary_artifacts"
    if p in {
        "artifacts/cgkn_naming_consistency_report.md",
        "artifacts/continuous_generation_current_gaps.md",
        "artifacts/continuous_generation_iterations.jsonl",
        "artifacts/reference_answer_trial.json",
        "artifacts/reference_answer_trial_summary.md",
        "artifacts/reference_answer_gap_analysis.md",
        "artifacts/reference_answer_repair_plan.md",
        "artifacts/complexity_scale_acceptance.json",
        "artifacts/complexity_scale_acceptance_report.md",
        "artifacts/complexity_scale_gap_analysis.md",
        "artifacts/complexity_scale_run_summary.json",
        "artifacts/complexity_scale_run_summary.md",
        "artifacts/requirement_decision_benchmark.json",
        "artifacts/requirement_decision_benchmark_summary.md",
    }:
        return "D_necessary_artifacts"
    if p.startswith("artifacts/reference_answer_project_trial_runs/") or p.startswith("artifacts/requirement_decision_benchmark_runs/") or p.startswith("artifacts/customer_agent_long_journey_runs/"):
        return "E_runtime_generated_artifacts"
    if p.startswith("artifacts/tmp_") or p in {"artifacts/write_probe.txt", "artifacts/pytest_progress.jsonl", "artifacts/pytest_collect_full.txt", "artifacts/complexity_scale_file_inventory.txt"}:
        return "G_should_not_commit_temporary_outputs"
    if p.startswith("artifacts/"):
        return "E_runtime_generated_artifacts"
    return "review_required"


def classify_dirty_files(root: pathlib.Path = ROOT) -> dict[str, Any]:
    rows = git_status_porcelain(root)
    categories: dict[str, list[dict[str, str]]] = {
        "A_core_code": [],
        "B_test_code": [],
        "C_docs": [],
        "D_necessary_artifacts": [],
        "E_runtime_generated_artifacts": [],
        "F_examples_project_memory_or_historical_dirty": [],
        "G_should_not_commit_temporary_outputs": [],
        "review_required": [],
    }
    for row in rows:
        categories[classify_path(row["path"])].append(row)
    recommended = [row["path"] for key in ("A_core_code", "B_test_code", "C_docs", "D_necessary_artifacts") for row in categories[key] if row["path"] in RECOMMENDED_COMMIT_FILES]
    exclude = [row["path"] for key in ("E_runtime_generated_artifacts", "F_examples_project_memory_or_historical_dirty", "G_should_not_commit_temporary_outputs") for row in categories[key]]
    review = [row["path"] for row in categories["review_required"]]
    return {
        "created_at": now(),
        "dirty_count": len(rows),
        "categories": categories,
        "recommended_commit_files": sorted(dict.fromkeys(recommended)),
        "recommended_exclude_files": sorted(dict.fromkeys(exclude)),
        "review_required_files": sorted(dict.fromkeys(review)),
    }


def write_classification_reports(doc: dict[str, Any]) -> None:
    write_json(CLASSIFICATION_JSON, doc)
    lines = [
        "# Release Candidate File Classification",
        "",
        f"- dirty_count: `{doc.get('dirty_count')}`",
        "- policy: do not commit runtime/generated outputs in bulk; review unknown dirty files.",
        "",
    ]
    categories = doc.get("categories", {})
    for key, rows in categories.items() if isinstance(categories, dict) else []:
        lines.extend([f"## {key}", ""])
        if rows:
            lines.extend(f"- `{item.get('status')} {item.get('path')}`" for item in rows if isinstance(item, dict))
        else:
            lines.append("- none")
        lines.append("")
    lines.extend(["## Recommended Commit Files", ""])
    recommended = list(doc.get("recommended_commit_files", []))
    lines.extend(f"- `{item}`" for item in recommended) if recommended else lines.append("- none")
    lines.extend(["", "## Recommended Exclude Files", ""])
    excluded = list(doc.get("recommended_exclude_files", [])[:400])
    lines.extend(f"- `{item}`" for item in excluded) if excluded else lines.append("- none")
    lines.extend(["", "## Review Required", ""])
    review = list(doc.get("review_required_files", []))
    lines.extend(f"- `{item}`" for item in review) if review else lines.append("- none")
    CLASSIFICATION_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def status_pass(value: Any) -> bool:
    return str(value).upper() in {"PASS", "CUSTOMER_ACCEPTED", "RELEASE_CANDIDATE_READY"}


def evaluate_release_candidate(root: pathlib.Path = ROOT) -> dict[str, Any]:
    artifacts = root / "artifacts"
    requirement = read_json(artifacts / "requirement_decision_benchmark.json")
    complexity = read_json(artifacts / "complexity_scale_acceptance.json")
    customer_trial = read_json(artifacts / "customer_agent_long_journey_trial.json")
    customer_score = read_json(artifacts / "customer_agent_scorecard.json")
    reference = read_json(artifacts / "reference_answer_trial.json")
    naming_report = read_text(artifacts / "cgkn_naming_consistency_report.md")
    full_pytest = read_json(artifacts / "full_pytest_result.json")
    classification = read_json(artifacts / "release_candidate_file_classification.json")
    readme = read_text(root / "README.md", limit=12000)
    docs_acceptance = read_text(root / "docs" / "release_candidate_acceptance.md")

    commercial = customer_score.get("commercial_readiness", {}) if isinstance(customer_score.get("commercial_readiness"), dict) else {}
    reference_commercial = reference.get("commercial_readiness", {}) if isinstance(reference.get("commercial_readiness"), dict) else {}
    delivery = customer_score.get("delivery_evidence", {}) if isinstance(customer_score.get("delivery_evidence"), dict) else {}
    capability = customer_score.get("capability_evidence", {}) if isinstance(customer_score.get("capability_evidence"), dict) else {}
    checks = {
        "requirement_benchmark_pass": requirement.get("verdict") == "PASS" and int(requirement.get("score", 0) or 0) >= 90,
        "complexity_benchmark_pass": complexity.get("verdict") == "PASS" and int(complexity.get("overall_score", complexity.get("score", 0)) or 0) >= 90,
        "customer_agent_long_journey_pass": customer_score.get("verdict") == "CUSTOMER_ACCEPTED" and int(customer_score.get("total", 0) or 0) >= 90 and int(customer_trial.get("customer_journey_event_count", 0) or 0) >= 25,
        "reference_trial_pass": reference.get("score", {}).get("verdict") == "PASS" and int(reference.get("score", {}).get("total", 0) or 0) >= 90,
        "name_leak_and_cgkn_naming_pass": "status: `PASS`" in naming_report and reference.get("name_leak_scan", {}).get("status") == "PASS",
        "delivery_evidence_pass": delivery.get("status") == "PASS" and delivery.get("screenshot_ok") is True and delivery.get("zip_ok") is True,
        "artifact_integrity_pass": reference.get("artifact_integrity", {}).get("status") == "PASS" and customer_trial.get("artifact_integrity", {}).get("status") == "PASS",
        "full_pytest_pass": full_pytest.get("status") == "PASS" and int(full_pytest.get("passed", 0) or 0) >= 700,
        "commercial_ready_false_justified": commercial.get("commercial_ready") is False and reference_commercial.get("commercial_ready") is False and bool(commercial.get("why_not_commercial_ready")),
        "no_production_claim_without_evidence": capability.get("production_asr_claimed") is False and commercial.get("commercial_ready") is False,
        "known_gaps_explicit": (artifacts / "release_candidate_known_gaps.md").exists() or bool(reference.get("known_gaps")),
        "file_classification_exists": bool(classification.get("dirty_count") is not None),
        "readme_docs_use_cgkn_current_name": readme.startswith("# CGKN") and "Current product name: CGKN" in readme and "CGKN" in docs_acceptance,
        "dirty_generated_artifacts_classified": bool(classification.get("recommended_exclude_files") is not None),
    }
    blockers = [key for key, ok in checks.items() if not ok]
    if not blockers:
        verdict = "RELEASE_CANDIDATE_READY"
    elif len(blockers) <= 3 and checks.get("full_pytest_pass") and checks.get("commercial_ready_false_justified"):
        verdict = "RELEASE_CANDIDATE_WITH_GAPS"
    else:
        verdict = "NOT_READY"
    known_gaps = list(reference.get("known_gaps", [])) if isinstance(reference.get("known_gaps"), list) else []
    known_gaps.extend(customer_score.get("blockers", []) if isinstance(customer_score.get("blockers"), list) else [])
    if commercial.get("commercial_ready") is False:
        known_gaps.append("commercial_ready:false_until_representative_real_asr_reliability_and_human_review_evidence")
    return {
        "created_at": now(),
        "selected_gap": "release_candidate_cleanup_and_long_run_final_validation_missing",
        "verdict": verdict,
        "checks": checks,
        "blockers": blockers,
        "requirement_benchmark": {"score": requirement.get("score"), "verdict": requirement.get("verdict")},
        "complexity_benchmark": {"score": complexity.get("overall_score", complexity.get("score")), "verdict": complexity.get("verdict")},
        "customer_agent": {
            "score": customer_score.get("total"),
            "verdict": customer_score.get("verdict"),
            "events": customer_trial.get("customer_journey_event_count"),
            "challenge_count": customer_score.get("customer_challenge_count"),
            "rework_request_count": customer_score.get("rework_request_count"),
        },
        "reference_answer_trial": {
            "score": reference.get("score", {}).get("total"),
            "verdict": reference.get("score", {}).get("verdict"),
            "generated_project_path": reference.get("generated_project_path"),
            "selected_requirement": reference.get("selected_requirement", {}).get("selected_requirement_name"),
            "name_leak_status": reference.get("name_leak_scan", {}).get("status"),
        },
        "delivery_evidence": delivery,
        "capability_evidence": capability,
        "commercial_readiness": commercial,
        "full_pytest": full_pytest,
        "known_gaps": sorted(dict.fromkeys(str(item) for item in known_gaps if str(item).strip())),
        "next_recommended_action": "Collect representative real ASR, reference transcripts, reliability runs, and approved human review evidence before any commercial_ready=true claim.",
    }


def write_release_docs(result: dict[str, Any]) -> None:
    write_json(ACCEPTANCE_JSON, result)
    commercial = result.get("commercial_readiness", {})
    lines = [
        "# CGKN Release Candidate Summary",
        "",
        f"- verdict: `{result.get('verdict')}`",
        "- current goal: Requirement Decision First + complex local project generation + customer-agent long journey validation + evidence-based delivery + honest commercial readiness gating.",
        f"- requirement benchmark: `{result.get('requirement_benchmark', {}).get('verdict')}` score `{result.get('requirement_benchmark', {}).get('score')}`",
        f"- complexity benchmark: `{result.get('complexity_benchmark', {}).get('verdict')}` score `{result.get('complexity_benchmark', {}).get('score')}`",
        f"- customer-agent long journey: `{result.get('customer_agent', {}).get('verdict')}` score `{result.get('customer_agent', {}).get('score')}` events `{result.get('customer_agent', {}).get('events')}`",
        f"- reference answer trial: `{result.get('reference_answer_trial', {}).get('verdict')}` score `{result.get('reference_answer_trial', {}).get('score')}`",
        f"- delivery evidence: `{result.get('delivery_evidence', {}).get('status')}`",
        f"- capability evidence: `{result.get('capability_evidence', {}).get('status')}`",
        f"- commercial readiness: `{commercial.get('status')}`",
        f"- commercial_ready: `{commercial.get('commercial_ready')}`",
        f"- why not commercial ready: {commercial.get('why_not_commercial_ready')}",
        "",
        "CGKN is not claimed as commercial production ASR ready. Fixture, placeholder, contract-only, and degraded capabilities remain explicitly non-production evidence.",
    ]
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    gaps = ["# CGKN Release Candidate Known Gaps", ""]
    for gap in result.get("known_gaps", []):
        gaps.append(f"- {gap}")
    KNOWN_GAPS_MD.write_text("\n".join(gaps) + "\n", encoding="utf-8")


def write_acceptance_doc() -> None:
    path = ROOT / "docs" / "release_candidate_acceptance.md"
    text = """# CGKN Release Candidate Acceptance

CGKN is release-candidate ready when the current system can demonstrate Requirement Decision First, complex local project generation, customer-agent long journey validation, evidence-based delivery, and honest commercial readiness gating.

Release candidate readiness does not mean commercial production ASR readiness. `commercial_ready` must remain `false` until representative real ASR evidence, reference transcripts, repeat reliability runs, approved human review evidence, artifact integrity, and delivery evidence all pass.

The release candidate gate checks requirement benchmark results, complexity benchmark results, customer-agent long journey artifacts, reference-answer trial artifacts, naming consistency, delivery evidence, artifact integrity, full pytest evidence, known gaps, and dirty worktree classification.
"""
    path.write_text(text, encoding="utf-8")


def write_commit_plan(classification: dict[str, Any], result: dict[str, Any]) -> None:
    lines = [
        "# CGKN Release Candidate Commit Plan",
        "",
        "## Recommendation",
        "",
        "- Do not commit all dirty files in bulk.",
        "- Commit source, tests, docs, and selected summary artifacts needed for review.",
        "- Exclude runtime run directories, generated trial run trees, historical project memory churn, and temporary probe files unless a reviewer explicitly requests them.",
        "- Suggested commit message: `Prepare CGKN release candidate validation`",
        "- Suggested PR title: `Prepare CGKN release candidate validation`",
        "",
        "## Suggested Commit Files",
        "",
    ]
    commit_files = classification.get("recommended_commit_files", [])
    lines.extend(f"- `{item}`" for item in commit_files) if commit_files else lines.append("- none")
    lines.extend(["", "## Suggested Exclude Files", ""])
    excluded = list(classification.get("recommended_exclude_files", [])[:400])
    lines.extend(f"- `{item}`" for item in excluded) if excluded else lines.append("- none")
    lines.extend(["", "## Review Required Files", ""])
    review = list(classification.get("review_required_files", []))
    lines.extend(f"- `{item}`" for item in review) if review else lines.append("- none")
    lines.extend(
        [
            "",
            "## Suggested PR Description",
            "",
            "### What changed",
            "- Added Customer-Agent Long Journey validation and release candidate gate artifacts.",
            "- Added dirty worktree classification and release candidate acceptance reports.",
            "- Updated CGKN naming in customer-facing README/docs.",
            "",
            "### Why",
            "- Move CGKN from feature accumulation to an auditable release-candidate validation state.",
            "",
            "### Validation",
            f"- Release candidate verdict: `{result.get('verdict')}`",
            f"- Customer-Agent Long Journey: `{result.get('customer_agent', {}).get('verdict')}` score `{result.get('customer_agent', {}).get('score')}`",
            f"- Commercial readiness: `{result.get('commercial_readiness', {}).get('status')}`, commercial_ready `{result.get('commercial_readiness', {}).get('commercial_ready')}`",
            "",
            "### Known gaps",
            "- Commercial production ASR readiness still requires representative real ASR evidence, reference transcripts, reliability runs, and approved human review evidence.",
            "",
            "### What is not claimed",
            "- This PR does not claim production ASR or commercial_ready=true.",
        ]
    )
    COMMIT_PLAN_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_gate(root: pathlib.Path = ROOT, *, record_loop: bool = True) -> dict[str, Any]:
    write_acceptance_doc()
    classification = classify_dirty_files(root)
    write_classification_reports(classification)
    result = evaluate_release_candidate(root)
    write_release_docs(result)
    write_commit_plan(classification, result)
    if record_loop:
        continuous_generation_ledger.append_iteration(
            {
                "selected_gap": "release_candidate_cleanup_and_long_run_final_validation_missing",
                "layer": "test_infrastructure",
                "reason_for_priority": "Release candidate gate consolidates benchmark, customer-agent, delivery, commercial readiness, naming, full pytest, and dirty classification evidence.",
                "micro_plan": ["classify dirty files", "read validation artifacts", "evaluate RC checks", "write summary, known gaps, and commit plan"],
                "acceptance_criteria": list(result.get("checks", {}).keys()),
                "files_changed": [
                    "docs/release_candidate_acceptance.md",
                    "scripts/release_candidate_gate.py",
                    "tests/test_release_candidate_gate.py",
                    "artifacts/release_candidate_acceptance.json",
                    "artifacts/release_candidate_summary.md",
                    "artifacts/release_candidate_known_gaps.md",
                    "artifacts/release_candidate_file_classification.json",
                    "artifacts/release_candidate_file_classification.md",
                    "artifacts/release_candidate_commit_plan.md",
                ],
                "tests_added_or_updated": ["tests/test_release_candidate_gate.py"],
                "commands_run": ["python scripts/release_candidate_gate.py"],
                "test_results": [{"name": "release_candidate_gate", "status": result["verdict"]}],
                "benchmark_results": [
                    {"name": "requirement_decision", **result.get("requirement_benchmark", {})},
                    {"name": "complexity_scale", **result.get("complexity_benchmark", {})},
                ],
                "known_gaps_after_iteration": result.get("known_gaps", []),
                "next_recommended_action": result.get("next_recommended_action", ""),
                "status": "PASS" if result.get("verdict") == "RELEASE_CANDIDATE_READY" else "PARTIAL",
            },
            root / "artifacts" / "continuous_generation_iterations.jsonl",
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-record-loop", action="store_true")
    args = parser.parse_args()
    result = run_gate(ROOT, record_loop=not args.no_record_loop)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"RELEASE_CANDIDATE_GATE: {result['verdict']}")
        print(f"summary={SUMMARY_MD}")
        print(f"acceptance={ACCEPTANCE_JSON}")
        if result.get("blockers"):
            print("blockers=" + ",".join(result["blockers"]))
    return 0 if result["verdict"] == "RELEASE_CANDIDATE_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
