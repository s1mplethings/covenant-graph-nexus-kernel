#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import continuous_generation_ledger
import canonical_repo_publish


CLASSIFICATION_JSON = ARTIFACTS / "release_candidate_file_classification.json"
CLASSIFICATION_MD = ARTIFACTS / "release_candidate_file_classification.md"
ACCEPTANCE_JSON = ARTIFACTS / "release_candidate_acceptance.json"
SUMMARY_MD = ARTIFACTS / "release_candidate_summary.md"
KNOWN_GAPS_MD = ARTIFACTS / "release_candidate_known_gaps.md"


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


def classify_dirty_files(root: pathlib.Path = ROOT) -> dict[str, Any]:
    """Compatibility report delegated to the canonical publish classifier."""
    manifest = canonical_repo_publish.build_change_manifest(root)
    categories: dict[str, list[dict[str, str]]] = {}
    for row in manifest["files"]:
        categories.setdefault(row["classification"], []).append(row)
    return {
        "created_at": now(),
        "dirty_count": len(manifest["files"]),
        "categories": categories,
        "recommended_commit_files": manifest["commit_files"],
        "recommended_exclude_files": manifest["excluded_files"],
        "review_required_files": manifest["review_required_files"] + manifest["blocked_files"],
        "change_manifest_hash": manifest["change_manifest_hash"],
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


def run_gate(root: pathlib.Path = ROOT, *, record_loop: bool = True) -> dict[str, Any]:
    write_acceptance_doc()
    classification = classify_dirty_files(root)
    write_classification_reports(classification)
    result = evaluate_release_candidate(root)
    write_release_docs(result)
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
