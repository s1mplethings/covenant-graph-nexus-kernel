#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import product_design_depth_governance as governance
from scripts import product_design_depth_rule_guard


FROZEN_AT = "2026-09-14T00:00:00+00:00"
RESOURCE_HASH = "sha256:" + "a" * 64


def _role(output: pathlib.Path) -> dict[str, Any]:
    return governance.freeze_preimplementation_governance(
        "本地应用从电视剧视频中根据参考图片识别同一真实人物，复核并导出全部角色片段",
        {
            "capabilities": ["真实人物身份识别", "视频分析", "人工复核", "MP4 导出"],
            "target_users": ["本地视频剪辑用户"],
            "user_flows": ["导入目录", "选择参考帧", "后台分析", "复核", "导出"],
        },
        {"workstreams": ["local UI", "identity recognition", "persistence", "video export"]},
        output / "contracts" / "role_clip",
        frozen_resource_hashes=[RESOURCE_HASH],
        frozen_at=FROZEN_AT,
    )


def _profile(goal: str, capabilities: list[str], flows: list[str], workstreams: list[str], output: pathlib.Path) -> dict[str, Any]:
    return governance.freeze_preimplementation_governance(
        goal,
        {"capabilities": capabilities, "user_flows": flows},
        {"workstreams": workstreams},
        output,
        frozen_at=FROZEN_AT,
    )


def build_reports(output_dir: pathlib.Path, regression: dict[str, Any]) -> dict[str, Any]:
    output = pathlib.Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    role = _role(output)
    calculator = _profile(
        "简单计算器，支持加减乘除", ["正确计算"], ["输入", "结果"], ["direct core"], output / "contracts" / "calculator"
    )
    csv_tool = _profile(
        "本地 CSV 清洗工具，导入、按规则清洗、预览并导出",
        ["CSV 规则清洗", "预览", "导出"], ["导入", "清洗", "预览", "导出"],
        ["parser", "rules", "export"], output / "contracts" / "csv",
    )
    high_risk = _profile(
        "批量处理并不可逆覆盖、删除用户原始数据",
        ["批量转换", "删除原始数据"], ["选择", "处理", "恢复"],
        ["worker", "recovery"], output / "contracts" / "high_risk",
    )
    overdesigned = _profile(
        "简单计算器，支持加减乘除", ["正确计算"], ["输入", "结果"],
        ["microservice", "kubernetes", "message queue", "distributed database"],
        output / "contracts" / "overdesigned_calculator",
    )

    proxy_project = output / "scenarios" / "color_proxy_project"
    proxy_project.mkdir(parents=True, exist_ok=True)
    (proxy_project / "recognizer.py").write_text(
        "def dominant_hue(frame):\n    return 'red'\n\ndef identity_match(frame):\n    return dominant_hue(frame) == 'red'\n",
        encoding="utf-8",
    )
    proxy_reports = governance.evaluate_and_write_project_reports(
        proxy_project,
        role,
        test_evidence={
            "status": "PASS",
            "resource_types": ["synthetic"],
            "repair_rounds_only_improved_synthetic": True,
        },
        delivery_allowed=True,
    )

    target_project = output / "scenarios" / "real_identity_project"
    target_project.mkdir(parents=True, exist_ok=True)
    (target_project / "recognizer.py").write_text(
        "identity_embedding = arcface(frame)\n",
        encoding="utf-8",
    )
    challenge_ids = [row["challenge_id"] for row in role["documents"]["challenge_matrix"]["challenges"]]
    independent = governance.produce_independent_product_evidence(
        real_world=True,
        representative=True,
        holdout_passed=True,
        challenge_ids_passed=challenge_ids,
        frozen_resource_hashes=[RESOURCE_HASH],
    )
    target_reports = governance.evaluate_product_maturity(
        role,
        target_project,
        test_evidence={"status": "PASS", "resource_types": ["real_world"]},
        independent_evidence=independent,
        delivery_allowed=True,
    )

    documents = role["documents"]
    governance.write_json(output / "goal_fidelity_contract_example.json", documents["goal_fidelity_contract"])
    governance.write_json(
        output / "project_complexity_profile_examples.json",
        {
            "kind": "CGKNProjectComplexityProfileExamples",
            "profiles": {
                "calculator": calculator["documents"]["project_complexity_profile"],
                "csv_cleaner": csv_tool["documents"]["project_complexity_profile"],
                "role_clip": documents["project_complexity_profile"],
                "destructive_data": high_risk["documents"]["project_complexity_profile"],
            },
            "expected_levels": {"calculator": "SIMPLE", "csv_cleaner": "STANDARD", "role_clip": "COMPLEX", "destructive_data": "HIGH_RISK"},
        },
    )
    governance.write_json(output / "core_difficulty_lock_example.json", documents["core_difficulty_lock"])
    governance.write_json(
        output / "proxy_solution_gate_report.json",
        {
            "kind": "CGKNProxySolutionGateAcceptanceReport",
            "color_proxy": proxy_reports["reports"]["proxy_solution_report"],
            "target_identity": target_reports["proxy_solution_report"],
            "gate_result": "PASS" if proxy_reports["reports"]["product_maturity_report"]["maturity_level"] == "PROTOTYPE" else "FAIL",
        },
    )
    governance.write_json(output / "test_realism_contract_example.json", documents["test_realism_contract"])
    governance.write_json(output / "challenge_matrix_example.json", documents["challenge_matrix"])
    governance.write_json(output / "product_maturity_report.json", proxy_reports["reports"]["product_maturity_report"])
    governance.write_json(output / "public_claim_policy_report.json", proxy_reports["reports"]["public_claim_policy_report"])
    governance.write_json(
        output / "overengineering_check_report.json",
        {
            "kind": "CGKNOverengineeringAcceptanceReport",
            "direct_calculator": calculator["documents"]["overengineering_check_report"],
            "overdesigned_calculator": overdesigned["documents"]["overengineering_check_report"],
            "csv_cleaner": csv_tool["documents"]["overengineering_check_report"],
            "status": "PASS",
        },
    )
    governance.write_json(output / "regression_report.json", regression)

    rule_guard = product_design_depth_rule_guard.inspect()
    conditions = {
        "role_proxy_capped_at_prototype": proxy_reports["reports"]["product_maturity_report"]["maturity_verdict"] == "PROTOTYPE_PASS",
        "proxy_target_goal_false": proxy_reports["reports"]["product_maturity_report"]["target_goal_satisfied"] is False,
        "representative_holdout_upgrades": target_reports["product_maturity_report"]["maturity_verdict"] == "TARGET_VALIDATED_PASS",
        "complexity_depth_is_risk_driven": documents["project_complexity_profile"]["complexity_level"] == "COMPLEX",
        "simple_project_stays_simple": calculator["documents"]["project_complexity_profile"]["complexity_level"] == "SIMPLE",
        "csv_project_stays_standard": csv_tool["documents"]["project_complexity_profile"]["complexity_level"] == "STANDARD",
        "high_risk_escalates": high_risk["documents"]["project_complexity_profile"]["complexity_level"] == "HIGH_RISK",
        "overengineering_rejected": overdesigned["documents"]["overengineering_check_report"]["verdict"] == "REPLAN_SIMPLER",
        "regression_passed": regression.get("status") == "PASS",
        "frozen_boundaries_unchanged": rule_guard["status"] == "PASS",
        "provider_calls_zero": int(regression.get("provider_calls", -1)) == 0,
    }
    verdict = "PRODUCT_DESIGN_DEPTH_GOVERNANCE_PASS" if all(conditions.values()) else "PRODUCT_DESIGN_DEPTH_GOVERNANCE_FAIL"
    final = {
        "kind": "CGKNProductDesignDepthGovernanceFinalVerdict",
        "verdict": verdict,
        "conditions": conditions,
        "rule_guard": rule_guard,
        "provider_calls": 0,
        "report_files": sorted(path.name for path in output.glob("*.json")) + ["final_verdict.json"],
        "created_at": FROZEN_AT,
    }
    governance.write_json(output / "final_verdict.json", final)
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--regression", required=True)
    args = parser.parse_args()
    regression = json.loads(pathlib.Path(args.regression).read_text(encoding="utf-8"))
    result = build_reports(pathlib.Path(args.output), regression)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["verdict"] == "PRODUCT_DESIGN_DEPTH_GOVERNANCE_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
