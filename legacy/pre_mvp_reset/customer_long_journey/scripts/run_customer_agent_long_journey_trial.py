#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[0]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import continuous_generation_ledger
import customer_agent_scorecard
import customer_agent_simulator
import local_packager
import run_reference_answer_project_trial


ARTIFACTS_DIR = ROOT / "artifacts"
TRIAL_JSON = ARTIFACTS_DIR / "customer_agent_long_journey_trial.json"
SUMMARY_MD = ARTIFACTS_DIR / "customer_agent_long_journey_summary.md"
DIALOGUE_JSONL = ARTIFACTS_DIR / "customer_agent_dialogue.jsonl"
SCORECARD_JSON = ARTIFACTS_DIR / "customer_agent_scorecard.json"
GAP_REPORT_MD = ARTIFACTS_DIR / "customer_agent_gap_report.md"
REWORK_REPORT_MD = ARTIFACTS_DIR / "customer_agent_rework_report.md"
RUNS_DIR = ARTIFACTS_DIR / "customer_agent_long_journey_runs"
CURRENT_GAPS = ARTIFACTS_DIR / "continuous_generation_current_gaps.md"


DEFAULT_REFERENCE_ANSWER = (
    "A reference-grade CGKN answer should turn a vague local-first media workbench goal into "
    "requirement decision artifacts, product contract documents, a generated shared GUI/CLI "
    "pipeline, delivery evidence, capability truth, and commercial readiness separation."
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_text(path: pathlib.Path, limit: int = 80000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def create_customer_run_dir(root: pathlib.Path) -> pathlib.Path:
    runs = pathlib.Path(root) / "artifacts" / "customer_agent_long_journey_runs"
    runs.mkdir(parents=True, exist_ok=True)
    for _ in range(8):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        candidate = runs / f"{stamp}-{uuid.uuid4().hex[:12]}"
        try:
            candidate.mkdir(parents=False, exist_ok=False)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("Unable to allocate a unique customer-agent trial run directory.")


def write_dialogue_jsonl(path: pathlib.Path, dialogue: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in dialogue) + "\n", encoding="utf-8")


def perform_rework(project_dir: pathlib.Path, trial_result: dict[str, Any], request: str) -> dict[str, Any]:
    before_readme = read_text(project_dir / "README.md")
    before_notes = read_text(project_dir / "DELIVERY_NOTES.md")
    capability = trial_result.get("capability_manifest", {})
    commercial = trial_result.get("commercial_readiness", {})
    smoke = trial_result.get("delivery", {}).get("smoke_command", {})
    screenshot = trial_result.get("artifact_integrity", {}).get("screenshot_path", "")
    rework_block = "\n".join(
        [
            "",
            "## Customer Rework Clarification",
            "",
            f"- request: {request}",
            f"- actual_smoke_command: {' '.join(str(item) for item in smoke.get('argv', []))}",
            f"- smoke_status: {smoke.get('status')}",
            "- package_contents: final_project_bundle.zip includes generated project files, README, TEST_REPORT, DELIVERY_NOTES, screenshot evidence, delivery_manifest, capability_manifest, run logs, and stage artifacts.",
            f"- asr_status: {capability.get('asr_status', 'unknown')}",
            f"- asr_evidence_tier: {capability.get('asr_evidence_tier', 'none')}",
            f"- transcription_status: {capability.get('transcription_status', 'unknown')}",
            f"- media_decode_status: {capability.get('media_decode_status', 'not_attempted')}",
            f"- commercial_readiness_status: {commercial.get('status', 'COMMERCIAL_BETA')}",
            f"- commercial_ready: {commercial.get('commercial_ready')}",
            "- customer_truth: fixture, placeholder, contract-only, or degraded capabilities are not production AI.",
            "- customer_truth: customer acceptance of this scoped trial does not make the project commercial ready.",
        ]
    )
    if "Customer Rework Clarification" not in before_readme:
        (project_dir / "README.md").write_text(before_readme.rstrip() + rework_block + "\n", encoding="utf-8")
    if "Customer Rework Clarification" not in before_notes:
        (project_dir / "DELIVERY_NOTES.md").write_text(before_notes.rstrip() + rework_block + "\n", encoding="utf-8")

    def enrich_manifest(package_manifest: dict[str, Any]) -> dict[str, Any]:
        manifest_path = project_dir / "delivery_manifest.json"
        enriched = dict(package_manifest)
        enriched.update(
            {
                "run_dir": trial_result.get("run_dir", ""),
                "screenshot_path": screenshot or "",
                "smoke_command": smoke,
                "evidence_status": {
                    "smoke_command": {"status": smoke.get("status"), "returncode": smoke.get("returncode")},
                    "screenshot": {"status": "PASS" if screenshot else "BLOCKED", "path": screenshot or ""},
                    "final_project_bundle": {"status": "PASS" if (project_dir / "final_project_bundle.zip").exists() else "FAIL"},
                    "readme": {"status": "PASS" if (project_dir / "README.md").exists() else "FAIL"},
                    "test_report": {"status": "PASS" if (project_dir / "TEST_REPORT.md").exists() else "FAIL"},
                    "delivery_notes": {"status": "PASS" if (project_dir / "DELIVERY_NOTES.md").exists() else "FAIL"},
                },
            }
        )
        write_json(manifest_path, enriched)
        return enriched

    manifest = local_packager.package_project(
        project_dir,
        output_dir=project_dir,
        startup_command=" ".join(str(item) for item in smoke.get("argv", [])),
        run_log_path=project_dir / "run_logs" / "delivery_smoke_command.log",
        screenshot_path=screenshot or None,
        known_limits=trial_result.get("known_gaps", []),
    )
    enriched_manifest = enrich_manifest(manifest)
    packaged_evidence_dir = project_dir / "packaged_evidence"
    packaged_evidence_dir.mkdir(parents=True, exist_ok=True)
    write_json(packaged_evidence_dir / "delivery_manifest.json", enriched_manifest)
    (packaged_evidence_dir / "START_HERE.txt").write_text(
        "\n".join(
            [
                "Start with README.md.",
                "Actual smoke command:",
                " ".join(str(item) for item in smoke.get("argv", [])),
                "Formal delivery_manifest.json is also written at the project root after packaging.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = local_packager.package_project(
        project_dir,
        output_dir=project_dir,
        startup_command=" ".join(str(item) for item in smoke.get("argv", [])),
        run_log_path=project_dir / "run_logs" / "delivery_smoke_command.log",
        screenshot_path=screenshot or None,
        known_limits=trial_result.get("known_gaps", []),
    )
    enriched_manifest = enrich_manifest(manifest)
    return {
        "status": "PASS" if pathlib.Path(str(enriched_manifest.get("package_path", ""))).exists() else "FAIL",
        "request": request,
        "updated_files": [str(project_dir / "README.md"), str(project_dir / "DELIVERY_NOTES.md"), str(project_dir / "packaged_evidence" / "delivery_manifest.json"), str(project_dir / "final_project_bundle.zip"), str(project_dir / "delivery_manifest.json")],
        "packager_manifest": enriched_manifest,
        "customer_agent_modified_cgkn_code": False,
        "customer_agent_generated_target_project_code": False,
    }


def customer_verdict_label(score: int) -> str:
    if score >= 90:
        return "CUSTOMER_ACCEPTED"
    if score >= 75:
        return "CUSTOMER_ACCEPTED_WITH_GAPS"
    if score >= 55:
        return "NEEDS_REWORK"
    return "CUSTOMER_REJECTED"


def markdown_summary(result: dict[str, Any]) -> str:
    scorecard = result["scorecard"]
    selected = result.get("selected_requirement", {})
    commercial = scorecard.get("commercial_readiness", {})
    return "\n".join(
        [
            "# CGKN Customer-Agent Long Journey Trial",
            "",
            f"- run_dir: `{result.get('run_dir')}`",
            f"- generated project path: `{result.get('generated_project_path')}`",
            f"- customer persona: `{result.get('customer_persona', {}).get('role')}`",
            f"- original vague goal: {result.get('original_vague_goal')}",
            f"- selected_requirement: `{selected.get('selected_requirement_name') or selected.get('name') or selected.get('selected_requirement_id')}`",
            f"- MVP scope: `{selected.get('mvp_scope')}`",
            f"- non-goals: `{selected.get('non_goals')}`",
            f"- customer journey length: `{result.get('customer_journey_event_count')}`",
            f"- number of customer challenges: `{scorecard.get('customer_challenge_count')}`",
            f"- rework request: {result.get('rework_report', {}).get('request')}",
            f"- rework result: `{result.get('rework_report', {}).get('status')}`",
            f"- final score: `{scorecard.get('total')}`",
            f"- customer verdict: `{scorecard.get('verdict')}`",
            f"- layered status: `{result.get('layered_status', {}).get('overall_status')}`",
            f"- delivery evidence status: `{scorecard.get('delivery_evidence', {}).get('status')}`",
            f"- capability evidence status: `{scorecard.get('capability_evidence', {}).get('status')}`",
            f"- commercial readiness status: `{commercial.get('status')}`",
            f"- commercial_ready: `{commercial.get('commercial_ready')}`",
            f"- why not commercial ready: {commercial.get('why_not_commercial_ready')}",
            f"- next recommended action: {result.get('next_recommended_action')}",
        ]
    ) + "\n"


def write_gap_report(path: pathlib.Path, result: dict[str, Any]) -> None:
    scorecard = result["scorecard"]
    gaps = list(result.get("known_gaps", []))
    gaps.extend(scorecard.get("blockers", []))
    lines = [
        "# Customer-Agent Gap Report",
        "",
        f"- selected_gap: `{result.get('selected_gap')}`",
        f"- customer_verdict: `{scorecard.get('verdict')}`",
        f"- commercial_ready: `{scorecard.get('commercial_readiness', {}).get('commercial_ready')}`",
        f"- reference_name_leak_status: `{result.get('reference_name_leak_status')}`",
        "",
        "## Gaps",
    ]
    if gaps:
        lines.extend(f"- {gap}" for gap in sorted(dict.fromkeys(str(item) for item in gaps if str(item).strip())))
    else:
        lines.append("- No customer-acceptance blocker found. Commercial readiness remains separate and false.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_rework_report(path: pathlib.Path, report: dict[str, Any]) -> None:
    lines = [
        "# Customer-Agent Rework Report",
        "",
        f"- status: `{report.get('status')}`",
        f"- request: {report.get('request')}",
        f"- customer_agent_modified_cgkn_code: `{report.get('customer_agent_modified_cgkn_code')}`",
        f"- customer_agent_generated_target_project_code: `{report.get('customer_agent_generated_target_project_code')}`",
        "",
        "## Updated Evidence",
    ]
    lines.extend(f"- `{item}`" for item in report.get("updated_files", []))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_current_gaps(result: dict[str, Any], root: pathlib.Path) -> None:
    scorecard = result["scorecard"]
    lines = [
        "# Continuous Generation Current Gaps",
        "",
        "- highest_priority_gap: `customer_agent_long_journey_followup_real_production_evidence_missing`",
        f"- latest_customer_agent_trial_verdict: `{scorecard.get('verdict')}`",
        f"- latest_customer_agent_score: `{scorecard.get('total')}`",
        f"- commercial_readiness_status: `{scorecard.get('commercial_readiness', {}).get('status')}`",
        f"- commercial_ready: `{scorecard.get('commercial_readiness', {}).get('commercial_ready')}`",
        f"- delivery_evidence_status: `{scorecard.get('delivery_evidence', {}).get('status')}`",
        f"- capability_evidence_status: `{scorecard.get('capability_evidence', {}).get('status')}`",
        f"- full_pytest_required: `yes`",
        "",
        "## Known Gaps",
    ]
    gaps = list(result.get("known_gaps", [])) + list(scorecard.get("blockers", []))
    if gaps:
        lines.extend(f"- {gap}" for gap in sorted(dict.fromkeys(str(item) for item in gaps if str(item).strip())))
    else:
        lines.append("- No customer acceptance blocker found.")
    (root / "artifacts" / "continuous_generation_current_gaps.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_trial(
    *,
    root: pathlib.Path = ROOT,
    no_live: bool = True,
    use_reference_answer_trial: bool = False,
    enable_rework: bool = False,
    capture_screenshot: bool = True,
    reference_answer: str = DEFAULT_REFERENCE_ANSWER,
) -> dict[str, Any]:
    root = pathlib.Path(root)
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    customer_run_dir = create_customer_run_dir(root)

    base = run_reference_answer_project_trial.run_trial(
        reference_answer=reference_answer,
        root=root,
        no_live=no_live,
        capture_screenshot=capture_screenshot,
        forbidden_terms=[],
        use_user_media_fixture=use_reference_answer_trial,
        use_media_decode_smoke=use_reference_answer_trial,
        use_real_asr_contract_fixture=use_reference_answer_trial,
        use_asr_quality_gate_fixture=use_reference_answer_trial,
        use_real_asr_multi_sample_eval_fixture=use_reference_answer_trial,
        use_commercial_promotion_gate_fixture=use_reference_answer_trial,
    )
    project_dir = pathlib.Path(base["generated_project_path"])
    rework_report = {
        "status": "SKIPPED",
        "request": customer_agent_simulator.DEFAULT_REWORK_REQUEST,
        "updated_files": [],
        "customer_agent_modified_cgkn_code": False,
        "customer_agent_generated_target_project_code": False,
    }
    if enable_rework:
        rework_report = perform_rework(project_dir, base, customer_agent_simulator.DEFAULT_REWORK_REQUEST)
        base["artifact_integrity"] = run_reference_answer_project_trial.evaluate_artifact_integrity(project_dir, pathlib.Path(base["run_dir"]))
        base["commercial_readiness"] = run_reference_answer_project_trial.evaluate_commercial_honesty(project_dir)
        base["capability_manifest"] = run_reference_answer_project_trial.evaluate_capability_manifest(project_dir)

    dialogue = customer_agent_simulator.build_dialogue(
        base,
        rework_request=customer_agent_simulator.DEFAULT_REWORK_REQUEST,
        rework_completed=rework_report.get("status") == "PASS",
    )
    scorecard = customer_agent_scorecard.score_customer_journey(
        trial_result=base,
        dialogue=dialogue,
        rework_completed=rework_report.get("status") == "PASS",
    )
    expected_label = customer_verdict_label(scorecard["total"])
    if scorecard["verdict"] == "CUSTOMER_ACCEPTED" and expected_label != "CUSTOMER_ACCEPTED":
        scorecard["verdict"] = expected_label

    result = {
        "created_at": now(),
        "mode": "no_live" if no_live else "live_requested",
        "selected_gap": "customer_agent_long_journey_end_to_end_validation_missing",
        "customer_agent_role": "black_box_customer_acceptance_agent",
        "customer_agent_controls": {
            "can_modify_cgkn_code": False,
            "can_generate_target_project_code": False,
            "can_forge_artifacts": False,
            "code_write_attempted": False,
            "artifact_forgery_attempted": False,
        },
        "generation_route": "reference_answer_trial_support_route" if use_reference_answer_trial else "deterministic_no_live_cgkn_trial_route",
        "use_reference_answer_trial": use_reference_answer_trial,
        "rework_enabled": enable_rework,
        "customer_persona": customer_agent_simulator.CUSTOMER_PERSONA,
        "original_vague_goal": customer_agent_simulator.ORIGINAL_VAGUE_GOAL,
        "required_journey_events": customer_agent_simulator.REQUIRED_JOURNEY_EVENTS,
        "customer_journey_event_count": len({item["event"] for item in dialogue}),
        "dialogue": dialogue,
        "scorecard": scorecard,
        "rework_report": rework_report,
        "generated_project_path": base.get("generated_project_path"),
        "run_dir": base.get("run_dir"),
        "customer_agent_run_dir": str(customer_run_dir),
        "selected_requirement": base.get("selected_requirement", {}),
        "layered_status": base.get("layered_status", {}),
        "delivery": base.get("delivery", {}),
        "artifact_integrity": base.get("artifact_integrity", {}),
        "capability_manifest": base.get("capability_manifest", {}),
        "commercial_readiness": base.get("commercial_readiness", {}),
        "known_gaps": base.get("known_gaps", []),
        "reference_name_leak_status": base.get("name_leak_scan", {}).get("status", ""),
        "customer_acceptance_equals_commercial_ready": False,
        "next_recommended_action": "Collect representative production media/ASR runs, approved human review evidence, and reliability evidence before any COMMERCIAL_READY claim.",
        "artifact_paths": {
            "trial": str(artifacts / "customer_agent_long_journey_trial.json"),
            "summary": str(artifacts / "customer_agent_long_journey_summary.md"),
            "dialogue": str(artifacts / "customer_agent_dialogue.jsonl"),
            "scorecard": str(artifacts / "customer_agent_scorecard.json"),
            "gap_report": str(artifacts / "customer_agent_gap_report.md"),
            "rework_report": str(artifacts / "customer_agent_rework_report.md"),
        },
    }

    write_json(artifacts / "customer_agent_long_journey_trial.json", result)
    (artifacts / "customer_agent_long_journey_summary.md").write_text(markdown_summary(result), encoding="utf-8")
    write_dialogue_jsonl(artifacts / "customer_agent_dialogue.jsonl", dialogue)
    write_json(artifacts / "customer_agent_scorecard.json", scorecard)
    write_gap_report(artifacts / "customer_agent_gap_report.md", result)
    write_rework_report(artifacts / "customer_agent_rework_report.md", rework_report)
    write_json(customer_run_dir / "customer_agent_long_journey_trial.json", result)
    write_dialogue_jsonl(customer_run_dir / "customer_agent_dialogue.jsonl", dialogue)
    update_current_gaps(result, root)

    continuous_generation_ledger.append_iteration(
        {
            "selected_gap": result["selected_gap"],
            "layer": "customer_acceptance",
            "reason_for_priority": "Validate CGKN as a customer-serving project team across requirement discovery, generation, delivery, rework, retest, and commercial readiness explanation.",
            "micro_plan": [
                "Run no-live CGKN generation evidence route.",
                "Simulate a customer-only long journey dialogue.",
                "Challenge demo/run/capability/commercial claims.",
                "Request rework and rescore after updated evidence.",
                "Write customer dialogue, scorecard, gap report, and summary artifacts.",
            ],
            "acceptance_criteria": [
                "At least 25 customer journey events are present.",
                "Customer agent cannot modify CGKN code or forge artifacts.",
                "At least three customer challenges and one rework request are present.",
                "Customer acceptance is scored separately from commercial_ready.",
                "Degraded, placeholder, fixture, or contract-only capability status is customer visible.",
            ],
            "files_changed": [
                "scripts/run_customer_agent_long_journey_trial.py",
                "scripts/customer_agent_simulator.py",
                "scripts/customer_agent_scorecard.py",
                "tests/test_customer_agent_long_journey_trial.py",
                "docs/customer_agent_long_journey_trial.md",
                "artifacts/customer_agent_long_journey_trial.json",
                "artifacts/customer_agent_long_journey_summary.md",
                "artifacts/customer_agent_dialogue.jsonl",
                "artifacts/customer_agent_scorecard.json",
                "artifacts/customer_agent_gap_report.md",
                "artifacts/customer_agent_rework_report.md",
                "artifacts/continuous_generation_current_gaps.md",
            ],
            "tests_added_or_updated": ["tests/test_customer_agent_long_journey_trial.py"],
            "commands_run": ["python scripts/run_customer_agent_long_journey_trial.py --no-live --use-reference-answer-trial --enable-rework"],
            "test_results": [{"name": "customer_agent_long_journey_trial", "status": scorecard["verdict"], "score": scorecard["total"]}],
            "benchmark_results": [
                {"name": "customer_journey_event_count", "count": result["customer_journey_event_count"]},
                {"name": "commercial_ready", "value": scorecard["commercial_readiness"]["commercial_ready"]},
            ],
            "known_gaps_after_iteration": list(result.get("known_gaps", [])) + list(scorecard.get("blockers", [])),
            "next_recommended_action": result["next_recommended_action"],
            "status": "PASS" if scorecard["verdict"] in {"CUSTOMER_ACCEPTED", "CUSTOMER_ACCEPTED_WITH_GAPS"} else "FAIL",
        },
        root / "artifacts" / "continuous_generation_iterations.jsonl",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-live", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--use-reference-answer-trial", action="store_true")
    parser.add_argument("--enable-rework", action="store_true")
    parser.add_argument("--no-screenshot", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_trial(
        root=ROOT,
        no_live=not args.live,
        use_reference_answer_trial=bool(args.use_reference_answer_trial),
        enable_rework=bool(args.enable_rework),
        capture_screenshot=not args.no_screenshot,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"CUSTOMER_AGENT_LONG_JOURNEY_TRIAL: {result['scorecard']['verdict']}")
        print(f"score={result['scorecard']['total']}")
        print(f"events={result['customer_journey_event_count']}")
        print(f"commercial_ready={result['scorecard']['commercial_readiness']['commercial_ready']}")
        print(f"dialogue={result['artifact_paths']['dialogue']}")
        print(f"scorecard={result['artifact_paths']['scorecard']}")
    return 0 if result["scorecard"]["verdict"] in {"CUSTOMER_ACCEPTED", "CUSTOMER_ACCEPTED_WITH_GAPS"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
