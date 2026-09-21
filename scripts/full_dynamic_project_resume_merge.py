from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import local_packager
from scripts.agent_growth_merge_protocol import merge_branch_results
from scripts.agent_tree_contracts import read_json, write_json
from scripts.agent_tree_registry import agent_by_id
from scripts.run_full_dynamic_real_project_eval import (
    capture_runtime_visual_evidence,
    check_bundle_integrity,
    evaluate_full_public_delivery_gate,
    run_integration,
    run_project_pytest,
    write_delivery_notes,
)


BRANCHES = ("backend_branch_agent", "frontend_branch_agent", "test_branch_agent")


def merge_resume_branch(
    *,
    registry: dict[str, Any],
    parent_agent: str,
    out_dir: str | pathlib.Path,
    requested_children: list[str] | None = None,
) -> dict[str, Any]:
    if requested_children:
        pruned = [
            child
            for child in requested_children
            if agent_by_id(registry, child).get("status") == "pruned"
        ]
        if pruned:
            result = {
                "parent_agent": parent_agent,
                "merge_verdict": "FAIL",
                "classification": "pruned_leaf_used_in_merge",
                "pruned_children": pruned,
                "issues": [f"{leaf}:pruned" for leaf in pruned],
            }
            write_json(pathlib.Path(out_dir) / "merge_results" / f"{parent_agent}.json", result)
            return result
    result = merge_branch_results(registry=registry, parent_agent=parent_agent, out_dir=out_dir)
    result["classification"] = "branch_merge_pass" if result["merge_verdict"] == "PASS" else "branch_merge_failed_after_resume"
    write_json(pathlib.Path(out_dir) / "merge_results" / f"{parent_agent}.json", result)
    return result


def _skipped(out: pathlib.Path, filename: str, reason: str) -> dict[str, Any]:
    result = {"ran": False, "verdict": "SKIPPED", "reason": reason}
    write_json(out / filename, result)
    return result


def run_resume_merge(
    *,
    resume_root: str | pathlib.Path,
    out_dir: str | pathlib.Path,
    capture_visual: bool = True,
) -> dict[str, Any]:
    root = pathlib.Path(resume_root)
    out = pathlib.Path(out_dir)
    leaf_root = root / "leaf_resume"
    leaf_result = read_json(leaf_root / "leaf_resume_result.json", {})
    source_run = pathlib.Path(read_json(root / "resume_plan.json", {}).get("source_run_dir", ""))
    out.mkdir(parents=True, exist_ok=True)
    project = out / "generated_project"
    source_project = pathlib.Path(leaf_result.get("project_dir", root / "run_001" / "generated_project"))
    same_project = source_project.resolve() == project.resolve()
    if not same_project:
        if project.exists():
            shutil.rmtree(project)
        if source_project.exists():
            shutil.copytree(source_project, project)
    for directory in ("checkpoints", "scope_contracts"):
        source = leaf_root / directory
        if directory == "scope_contracts":
            source = source_run / directory
        if source.exists():
            shutil.copytree(source, out / directory, dirs_exist_ok=True)
    registry = read_json(leaf_root / "agent_tree_registry_after.json", {})

    branch_merges = {
        branch: merge_resume_branch(registry=registry, parent_agent=branch, out_dir=out)
        for branch in BRANCHES
    }
    all_branches_pass = all(item.get("merge_verdict") == "PASS" for item in branch_merges.values())
    if leaf_result.get("verdict") == "BLOCKED":
        integration = _skipped(out, "merge_results/integration_agent.json", "provider_unavailable_during_resume")
    elif not all_branches_pass:
        integration = _skipped(out, "merge_results/integration_agent.json", "branch_merge_failed_after_resume")
    else:
        integration = run_integration(out, branch_merges)

    if integration.get("verdict") != "PASS":
        tests = _skipped(out, "test_execution.json", "integration_not_passed")
    else:
        tests = run_project_pytest(out)
    if tests.get("verdict") != "PASS":
        visual = _skipped(out, "visual_evidence.json", "real_test_execution_not_passed")
    elif capture_visual:
        visual = capture_runtime_visual_evidence(out)
    else:
        visual = _skipped(out, "visual_evidence.json", "visual_capture_disabled")

    if visual.get("verdict") != "PASS":
        bundle = _skipped(out, "bundle_integrity_check.json", "visual_evidence_not_passed")
    else:
        write_delivery_notes(project)
        manifest = local_packager.package_project(
            project,
            output_dir=out,
            startup_command="python app/main.py --port 8765",
            screenshot_path=out / "screenshots" / "dashboard.png",
        )
        write_json(out / "delivery_manifest.json", manifest)
        bundle = check_bundle_integrity(out, out / "final_project_bundle.zip")

    if bundle.get("verdict") != "PASS":
        gate = _skipped(out, "public_delivery_gate.json", "bundle_integrity_not_passed")
        gate.update(
            {
                "delivery_allowed": False,
                "production_mainline": "support_lane_not_promoted",
                "sent_records": [],
            }
        )
        write_json(out / "public_delivery_gate.json", gate)
    else:
        gate = evaluate_full_public_delivery_gate(
            out,
            branch_merges=branch_merges,
            integration=integration,
            tests=tests,
            visual=visual,
            bundle=bundle,
        )
        gate["sent_records"] = []
        write_json(out / "public_delivery_gate.json", gate)

    if leaf_result.get("verdict") == "BLOCKED":
        classification, verdict = "provider_unavailable_during_resume", "BLOCKED"
    elif not all_branches_pass:
        classification, verdict = "branch_merge_failed_after_resume", "NEEDS_REWORK"
    elif integration.get("verdict") != "PASS":
        classification, verdict = "integration_failed_after_resume", "NEEDS_REWORK"
    elif tests.get("verdict") != "PASS":
        classification, verdict = "real_test_execution_failed_after_resume", "NEEDS_REWORK"
    elif visual.get("verdict") != "PASS":
        classification, verdict = "visual_evidence_failed_after_resume", "NEEDS_REWORK"
    elif bundle.get("verdict") != "PASS":
        classification, verdict = "bundle_integrity_failed_after_resume", "NEEDS_REWORK"
    elif gate.get("verdict") != "PASS":
        classification, verdict = "public_delivery_gate_failed_after_resume", "NEEDS_REWORK"
    else:
        classification, verdict = "full_dynamic_resume_project_pass", "PASS"
    result = {
        "classification": classification,
        "verdict": verdict,
        "branch_merges": {key: value.get("merge_verdict") for key, value in branch_merges.items()},
        "integration": integration,
        "real_test_execution": tests,
        "visual_evidence": visual,
        "bundle_integrity": bundle,
        "public_delivery_gate": gate,
        "production_mainline": "support_lane_not_promoted",
    }
    write_json(out / "resume_merge_result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = run_resume_merge(resume_root=args.resume_root, out_dir=args.out)
    print(json.dumps({"classification": result["classification"], "verdict": result["verdict"]}, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] in {"PASS", "BLOCKED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
