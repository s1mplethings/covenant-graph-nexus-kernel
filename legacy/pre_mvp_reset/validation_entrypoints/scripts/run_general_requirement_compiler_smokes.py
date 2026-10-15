#!/usr/bin/env python3
"""Run two fresh formal request/submit/resume smokes through requirement entry."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import canonical_goal_spec_compiler as compiler
import surrogate_provider_adapter as adapter


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def proposal(goal: str, *, core: list[str], outcome: str, workflow: str) -> dict[str, Any]:
    user = "the user who supplied the goal"
    workstreams = [
        {"id": f"capability_{index}", "scope": f"Implement and verify {capability}.", "covers_capabilities": [capability]}
        for index, capability in enumerate(core, start=1)
    ]
    values: dict[str, list[str]] = {
        "intended_users": [user],
        "desired_outcomes": [outcome],
        "proposed_core_capabilities": core,
        "proposed_supporting_capabilities": [],
        "proposed_user_workflows": [workflow],
        "explicit_constraints_found": compiler.extract_explicit_constraints(goal),
        "proposed_acceptance_anchors": [outcome],
        "proposed_forbidden_substitutions": ["Do not replace executable user outcomes with documentation, mock data, or an easier proxy."],
    }
    grounding: list[dict[str, str]] = []
    inferred = {"intended_users", "proposed_user_workflows", "proposed_forbidden_substitutions"}
    for field, items in values.items():
        for value in items:
            grounding.append({
                "target": field,
                "value": value,
                "source_kind": "NECESSARY_INFERENCE" if field in inferred else "RAW_GOAL",
                "source_excerpt": goal,
                "rationale": "This bounded source directly requires or necessarily supports the proposed requirement item.",
            })
    for row in workstreams:
        grounding.append({
            "target": "proposed_workstreams",
            "value": row["id"],
            "source_kind": "NECESSARY_INFERENCE",
            "source_excerpt": goal,
            "rationale": "This bounded workstream is necessary to implement one grounded core capability.",
        })
    return {
        "schema_version": "1.0",
        "interpreted_goal": goal,
        **values,
        "proposed_workstreams": workstreams,
        "necessary_inferences": [],
        "assumptions": ["Unspecified reversible interface details use conservative local defaults."],
        "open_questions": [],
        "source_grounding": grounding,
    }


def run_formal(project_root: pathlib.Path, goal: str, result_path: pathlib.Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable, str(ROOT / "scripts" / "run_codex_conversation_generation.py"),
            "--project-root", str(project_root), "--goal", goal,
            "--result", str(result_path), "--provider-mode", "codex_surrogate",
            "--timeout", "180", "--json",
        ],
        cwd=ROOT, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False,
    )
    if completed.returncode != 0 or not result_path.is_file():
        raise RuntimeError(f"formal smoke failed: {completed.returncode}: {completed.stderr[-2000:]}")
    return json.loads(result_path.read_text(encoding="utf-8"))


def smoke(report_root: pathlib.Path, name: str, goal: str, proposal_doc: dict[str, Any]) -> dict[str, Any]:
    identity = f"{name}-{uuid.uuid4().hex[:12]}"
    project_root = report_root / "runtime" / identity
    project_root.mkdir(parents=True, exist_ok=False)
    result_path = project_root / "formal_result.json"
    first = run_formal(project_root, goal, result_path)
    if first.get("status") != "WAITING_SURROGATE_RESPONSE":
        raise RuntimeError(f"{name}: initial requirement request not reached: {first.get('status')}")
    request_path = pathlib.Path(first["pending_requests"][0]["request_path"])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    response = adapter.build_response(request, json.dumps(proposal_doc, ensure_ascii=False), surrogate_identity="codex")
    receipt = adapter.submit_response(pathlib.Path(first["run_dir"]), response)
    second = run_formal(project_root, goal, result_path)
    pending_stages = [str(item.get("stage", "")) for item in second.get("pending_requests", []) if isinstance(item, dict)]
    requirement_checkpoint = pathlib.Path(first["run_dir"]) / "artifacts" / "requirement_decision_checkpoint.json"
    decision = json.loads(requirement_checkpoint.read_text(encoding="utf-8"))["result"] if requirement_checkpoint.is_file() else {}
    result = {
        "kind": "CGKNGeneralRequirementCompilerSmoke",
        "schema_version": "1.0",
        "name": name,
        "fresh_identity": identity,
        "goal": goal,
        "initial_status": first.get("status"),
        "submit_receipt": receipt,
        "resumed_status": second.get("status"),
        "resumed_workflow_state": second.get("workflow_state"),
        "pending_stages": pending_stages,
        "entered_formal_design": "product_design" in pending_stages,
        "requirement_status": decision.get("status", "NOT_EVALUATED"),
        "goal_spec_status": (decision.get("goal_spec", {}) or {}).get("status", "NOT_EVALUATED"),
        "goal_spec_hash": (decision.get("goal_spec", {}) or {}).get("goal_spec_hash", ""),
        "core_capabilities": (decision.get("goal_spec", {}) or {}).get("core_capabilities", []),
        "workstream_ids": [row.get("id") for row in (decision.get("project_plan", {}) or {}).get("workstreams", []) if isinstance(row, dict)],
        "run_id": first.get("run_id", ""),
        "project_id": first.get("candidate_id", ""),
        "run_dir": first.get("run_dir", ""),
        "project_root": str(project_root),
        "source_identity_ref": str((pathlib.Path(first["run_dir"]) / "artifacts" / "source_identity_report.json").resolve()),
        "provider_mode": second.get("provider_mode"),
        "real_provider_calls": second.get("real_provider_calls"),
        "network_attempts": second.get("network_attempts"),
        "provider_schedulers": second.get("provider_schedulers"),
        "status": "PASS" if receipt.get("accepted") and decision.get("status") == "PASS" and "product_design" in pending_stages else "FAIL",
        "generated_at": now(),
    }
    write_json(report_root / f"smoke_{name}_report.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-root", required=True)
    args = parser.parse_args()
    report_root = pathlib.Path(args.report_root).resolve()
    simple_goal = (
        "Create a local command-line text counter named textcounter. "
        "Implement count_text(text: str) -> dict and report character, word, and line counts as JSON. "
        "No GUI, network, database, or cloud."
    )
    unknown_goal = (
        "做一个完全本地运行的显微镜图像批次测量工具。用户导入一个图片目录，校准像素尺寸，"
        "测量细胞直径，人工排除错误轮廓，并导出带来源追踪的 CSV 报告；不得上传图像。"
    )
    unknown_goal = (
        "\u505a\u4e00\u4e2a\u5b8c\u5168\u672c\u5730\u8fd0\u884c\u7684\u663e\u5fae\u955c\u56fe\u50cf\u6279\u6b21\u6d4b\u91cf\u5de5\u5177\u3002"
        "\u7528\u6237\u5bfc\u5165\u4e00\u4e2a\u56fe\u7247\u76ee\u5f55\uff0c\u6821\u51c6\u50cf\u7d20\u5c3a\u5bf8\uff0c"
        "\u6d4b\u91cf\u7ec6\u80de\u76f4\u5f84\uff0c\u4eba\u5de5\u6392\u9664\u9519\u8bef\u8f6e\u5ed3\uff0c\u5e76\u5bfc\u51fa\u5e26\u6765\u6e90\u8ffd\u8e2a\u7684 CSV \u62a5\u544a\uff1b\u4e0d\u5f97\u4e0a\u4f20\u56fe\u50cf\u3002"
    )
    results = [
        smoke(report_root, "simple", simple_goal, proposal(
            simple_goal,
            core=["count_text"],
            outcome="Count characters, words, and lines from supplied UTF-8 text and return JSON.",
            workflow="provide UTF-8 text, run the counter, and review the JSON result",
        )),
        smoke(report_root, "unknown_domain", unknown_goal, proposal(
            unknown_goal,
            core=["import_microscope_images", "calibrate_pixel_size", "measure_cell_diameter", "review_contours", "export_traceable_csv"],
            outcome="从用户图像中得到可人工复核且可追踪来源的细胞直径 CSV。",
            workflow="导入图片目录，设置校准，运行测量，排除错误轮廓并导出 CSV",
        )),
    ]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item["status"] == "PASS" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
