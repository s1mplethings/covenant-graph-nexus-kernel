from __future__ import annotations

import json
import pathlib

from scripts import codex_conversation
from scripts import product_design_depth_governance as governance
from scripts import requirement_decision_lane


FROZEN_AT = "2026-09-14T00:00:00+00:00"
RESOURCE_HASH = "sha256:" + "a" * 64


def _role_governance(tmp_path: pathlib.Path, *, frozen_hashes: list[str] | None = None) -> dict:
    return governance.freeze_preimplementation_governance(
        "本地应用从电视剧视频中根据参考图片识别同一真实人物，复核并导出全部角色片段",
        {
            "capabilities": ["真实人物身份识别", "视频分析", "人工复核", "MP4 导出"],
            "target_users": ["本地视频剪辑用户"],
            "user_flows": ["导入目录", "选择参考帧", "后台分析", "复核", "导出"],
        },
        {"workstreams": ["local UI", "identity recognition", "persistence", "video export"]},
        tmp_path / "governance",
        frozen_resource_hashes=frozen_hashes,
        frozen_at=FROZEN_AT,
    )


def test_role_clip_goal_is_complex_and_not_request_length_driven(tmp_path: pathlib.Path) -> None:
    result = _role_governance(tmp_path)
    profile = result["documents"]["project_complexity_profile"]
    assert profile["complexity_level"] == "COMPLEX"
    assert profile["algorithmic_uncertainty"]["score"] == 3
    assert profile["real_world_variability"]["score"] == 3


def test_role_identity_is_a_locked_core_difficulty(tmp_path: pathlib.Path) -> None:
    result = _role_governance(tmp_path)
    fidelity = result["documents"]["goal_fidelity_contract"]
    lock = result["documents"]["core_difficulty_lock"]
    assert fidelity["non_negotiable_capabilities"] == ["real_person_identity_matching"]
    assert lock["difficulties"][0]["status"] == "LOCKED"
    assert "clothing" in " ".join(lock["difficulties"][0]["invalid_proxy_solutions"])


def test_role_challenges_break_color_and_fixture_proxies(tmp_path: pathlib.Path) -> None:
    matrix = _role_governance(tmp_path)["documents"]["challenge_matrix"]
    ids = {row["challenge_id"] for row in matrix["challenges"]}
    assert {"same_person_different_clothing", "different_person_same_color"} <= ids
    assert {"multi_person_frame", "target_absent", "nonidentical_reference_frame"} <= ids


def test_complex_realism_requires_variation_negative_control_and_holdout(tmp_path: pathlib.Path) -> None:
    realism = _role_governance(tmp_path)["documents"]["test_realism_contract"]
    assert realism["real_world_resources_required"] is True
    assert realism["synthetic_only_acceptance_allowed"] is False
    assert realism["holdout_required"] is True
    assert realism["negative_controls"]
    assert "holdout" in realism["required_resource_types"]


def test_color_identity_implementation_is_a_proxy(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "recognizer.py").write_text("def dominant_hue(frame): return 'red'\n", encoding="utf-8")
    report = governance.evaluate_proxy_solution(
        _role_governance(tmp_path),
        project,
        test_evidence={"status": "PASS", "resource_types": ["synthetic"]},
    )
    assert report["proxy_detected"] is True
    assert "appearance_color_identity_proxy" in report["proxy_type"]
    assert report["maximum_allowed_maturity"] == "PROTOTYPE"
    assert report["target_goal_satisfied"] is False


def test_synthetic_color_tests_cap_maturity_at_prototype(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "recognizer.py").write_text("def match(frame): return dominant_hue(frame) == 'red'\n", encoding="utf-8")
    reports = governance.evaluate_product_maturity(
        _role_governance(tmp_path),
        project,
        test_evidence={"status": "PASS", "resource_types": ["synthetic"]},
    )
    maturity = reports["product_maturity_report"]
    assert maturity["maturity_verdict"] == "PROTOTYPE_PASS"
    assert maturity["target_goal_satisfied"] is False
    assert maturity["real_world_validated"] is False


def test_no_representative_real_data_cannot_target_validate(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "recognizer.py").write_text("identity_embedding = object()\n", encoding="utf-8")
    reports = governance.evaluate_product_maturity(
        _role_governance(tmp_path), project, test_evidence={"status": "PASS"}
    )
    assert reports["product_maturity_report"]["maturity_level"] == "PROTOTYPE"


def test_independent_real_holdout_can_upgrade_identity_to_target_validated(tmp_path: pathlib.Path) -> None:
    product = _role_governance(tmp_path, frozen_hashes=[RESOURCE_HASH])
    project = tmp_path / "project"
    project.mkdir()
    (project / "recognizer.py").write_text("identity_embedding = arcface(frame)\n", encoding="utf-8")
    challenge_ids = [row["challenge_id"] for row in product["documents"]["challenge_matrix"]["challenges"]]
    evidence = governance.produce_independent_product_evidence(
        real_world=True,
        representative=True,
        holdout_passed=True,
        challenge_ids_passed=challenge_ids,
        frozen_resource_hashes=[RESOURCE_HASH],
    )
    reports = governance.evaluate_product_maturity(
        product,
        project,
        test_evidence={"status": "PASS", "resource_types": ["real_world"]},
        independent_evidence=evidence,
    )
    assert reports["product_maturity_report"]["maturity_verdict"] == "TARGET_VALIDATED_PASS"
    assert reports["product_maturity_report"]["target_goal_satisfied"] is True


def test_unfrozen_holdout_cannot_upgrade_complex_product(tmp_path: pathlib.Path) -> None:
    product = _role_governance(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / "recognizer.py").write_text("identity_embedding = arcface(frame)\n", encoding="utf-8")
    ids = [row["challenge_id"] for row in product["documents"]["challenge_matrix"]["challenges"]]
    evidence = governance.produce_independent_product_evidence(
        real_world=True, representative=True, holdout_passed=True,
        challenge_ids_passed=ids, frozen_resource_hashes=[RESOURCE_HASH],
    )
    maturity = governance.evaluate_product_maturity(
        product, project, test_evidence={"status": "PASS"}, independent_evidence=evidence
    )["product_maturity_report"]
    assert maturity["target_goal_satisfied"] is False
    assert "required challenge matrix incomplete" not in maturity["downgrade_reasons"]
    assert "FUNCTIONAL_MVP" == maturity["maturity_level"]


def test_production_ready_requires_all_hardening_checks(tmp_path: pathlib.Path) -> None:
    product = _role_governance(tmp_path, frozen_hashes=[RESOURCE_HASH])
    project = tmp_path / "project"
    project.mkdir()
    (project / "recognizer.py").write_text("identity_embedding = arcface(frame)\n", encoding="utf-8")
    ids = [row["challenge_id"] for row in product["documents"]["challenge_matrix"]["challenges"]]
    evidence = governance.produce_independent_product_evidence(
        real_world=True, representative=True, holdout_passed=True,
        challenge_ids_passed=ids, frozen_resource_hashes=[RESOURCE_HASH],
        production_checks={key: True for key in ("performance", "stability", "security", "recovery", "installation", "delivery")},
    )
    maturity = governance.evaluate_product_maturity(
        product, project, test_evidence={"status": "PASS"}, independent_evidence=evidence
    )["product_maturity_report"]
    assert maturity["maturity_verdict"] == "PRODUCTION_READY_PASS"


def test_delivery_allowed_remains_separate_from_target_satisfaction(tmp_path: pathlib.Path) -> None:
    product = _role_governance(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / "recognizer.py").write_text("appearance_color = 'blue'\n", encoding="utf-8")
    governance.evaluate_and_write_project_reports(
        project, product, test_evidence={"status": "PASS", "resource_types": ["synthetic"]}, delivery_allowed=True
    )
    gate = governance.attach_maturity_to_delivery_gate(
        {"verdict": "PASS_FINAL", "delivery_allowed": True}, project
    )
    assert gate["delivery_allowed"] is True
    assert gate["delivery_gate"] == "PASS_FINAL"
    assert gate["product_maturity"] == "PROTOTYPE"
    assert gate["target_goal_satisfied"] is False


def test_public_reply_names_appearance_proxy_prototype(tmp_path: pathlib.Path) -> None:
    product = _role_governance(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    (project / "recognizer.py").write_text("clothing_color = 'red'\n", encoding="utf-8")
    reports = governance.evaluate_and_write_project_reports(
        project, product, test_evidence={"status": "PASS", "resource_types": ["synthetic"]}, delivery_allowed=True
    )
    gate = governance.attach_maturity_to_delivery_gate(
        {"verdict": "PASS_FINAL", "delivery_allowed": True}, project
    )
    summary = codex_conversation.build_delivery_summary_text({"status": "ready"}, gate)
    assert "产品成熟度：PROTOTYPE" in summary
    assert "原始目标已验证：否" in summary
    assert "外观/颜色代理原型" in summary


def test_manual_review_cannot_mask_missing_automatic_core(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    report = governance.evaluate_proxy_solution(
        _role_governance(tmp_path), project,
        implementation_evidence={"manual_review_compensates_for_missing_core": True},
    )
    assert "manual_review_masks_core_failure" in report["proxy_type"]


def test_implementation_tailored_acceptance_is_detected(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    report = governance.evaluate_proxy_solution(
        _role_governance(tmp_path), project,
        test_evidence={"status": "PASS", "implementation_tailored_acceptance": True},
    )
    assert "implementation_tailored_acceptance" in report["proxy_type"]


def test_repeated_proxy_only_repairs_trigger_design_replan(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "recognizer.py").write_text("dominant_hue = 'red'\n", encoding="utf-8")
    report = governance.evaluate_product_maturity(
        _role_governance(tmp_path), project,
        test_evidence={"status": "PASS", "repair_rounds_only_improved_synthetic": True},
    )["design_replan_report"]
    assert report["status"] == "DESIGN_REPLAN_REQUIRED"
    assert report["component_wide_rollback"] is False
    assert "validated UI" in report["preserved_components"]


def test_holdout_and_architecture_failures_trigger_design_replan(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "recognizer.py").write_text("identity_embedding = arcface(frame)\n", encoding="utf-8")
    report = governance.evaluate_product_maturity(
        _role_governance(tmp_path), project,
        test_evidence={"status": "PASS", "consecutive_holdout_failures": 2, "architecture_supports_core": False},
    )["design_replan_report"]
    assert report["status"] == "DESIGN_REPLAN_REQUIRED"
    assert len(report["triggers"]) == 2


def test_simple_calculator_stays_simple_and_direct(tmp_path: pathlib.Path) -> None:
    result = governance.freeze_preimplementation_governance(
        "简单计算器，支持加减乘除",
        {"capabilities": ["正确计算"], "user_flows": ["输入表达式", "显示结果"]},
        {"workstreams": ["direct core"]},
        tmp_path / "calculator",
        frozen_at=FROZEN_AT,
    )
    assert result["documents"]["project_complexity_profile"]["complexity_level"] == "SIMPLE"
    assert result["documents"]["design_adequacy_report"]["required_alternatives"] == 1
    assert result["documents"]["overengineering_check_report"]["verdict"] == "PROPORTIONATE"


def test_simple_calculator_rejects_speculative_distributed_architecture(tmp_path: pathlib.Path) -> None:
    result = governance.freeze_preimplementation_governance(
        "简单计算器，支持加减乘除",
        {"capabilities": ["正确计算"], "user_flows": ["输入", "结果"]},
        {"workstreams": ["microservice", "kubernetes", "message queue"]},
        tmp_path / "calculator",
        frozen_at=FROZEN_AT,
    )
    check = result["documents"]["overengineering_check_report"]
    assert check["verdict"] == "REPLAN_SIMPLER"
    assert result["ready_to_implement"] is False


def test_csv_cleaner_is_standard_without_ml_queue_or_database(tmp_path: pathlib.Path) -> None:
    result = governance.freeze_preimplementation_governance(
        "本地 CSV 清洗工具，导入、按规则清洗、预览并导出",
        {"capabilities": ["CSV 规则清洗", "预览", "导出"], "user_flows": ["导入", "清洗", "预览", "导出"]},
        {"workstreams": ["parser", "rules", "export"]},
        tmp_path / "csv",
        frozen_at=FROZEN_AT,
    )
    assert result["documents"]["project_complexity_profile"]["complexity_level"] == "STANDARD"
    selected = result["documents"]["design_adequacy_report"]["selected_strategy"]
    assert selected == "direct_solution"
    assert result["documents"]["overengineering_check_report"]["unnecessary_components"] == []


def test_destructive_data_project_is_high_risk_with_recovery_design(tmp_path: pathlib.Path) -> None:
    result = governance.freeze_preimplementation_governance(
        "批量处理并不可逆覆盖、删除用户原始数据",
        {"capabilities": ["批量转换", "删除原始数据"], "user_flows": ["选择", "处理", "恢复"]},
        {"workstreams": ["worker", "recovery"]},
        tmp_path / "risky",
        frozen_at=FROZEN_AT,
    )
    assert result["documents"]["project_complexity_profile"]["complexity_level"] == "HIGH_RISK"
    adequacy = result["documents"]["design_adequacy_report"]
    assert adequacy["required_alternatives"] == 2
    assert "recovery" in adequacy["long_task_control"]
    challenge_ids = {row["challenge_id"] for row in result["documents"]["challenge_matrix"]["challenges"]}
    assert {"source_backup_preserved", "interrupted_write_atomicity", "rollback_recovery"} <= challenge_ids


def test_core_capability_deletion_blocks_challenge_review(tmp_path: pathlib.Path) -> None:
    product = _role_governance(tmp_path)
    docs = product["documents"]
    lock = dict(docs["core_difficulty_lock"])
    lock["difficulties"] = []
    review = governance.build_product_challenge_review(
        docs["goal_fidelity_contract"], docs["project_complexity_profile"], lock,
        docs["test_realism_contract"], docs["challenge_matrix"],
        docs["design_adequacy_report"], docs["overengineering_check_report"],
    )
    assert review["verdict"] == "REPLAN_CORE_CAPABILITY"
    assert review["implementation_entry_allowed"] is False


def test_contract_hash_rejects_post_freeze_acceptance_reduction(tmp_path: pathlib.Path) -> None:
    contract = _role_governance(tmp_path)["documents"]["goal_fidelity_contract"]
    assert governance.validate_artifact(contract)["status"] == "PASS"
    mutated = json.loads(json.dumps(contract, ensure_ascii=False))
    mutated["forbidden_simplifications"] = []
    assert governance.validate_artifact(mutated)["status"] == "NEEDS_REWORK"


def test_requirement_lane_freezes_governance_before_generation(tmp_path: pathlib.Path) -> None:
    result = requirement_decision_lane.run_requirement_decision(
        "为视频创作者构建本地 AI 切片工作台，处理长视频，根据参考图片识别同一真实人物并导出候选片段。",
        tmp_path / "run",
    )
    assert result["status"] == "PASS"
    assert result["ready_to_generate"] is True
    assert result["product_design_governance"]["review_verdict"] == "DESIGN_READY"
    assert result["acceptance_contract"]["product_design_depth_governance"]["frozen_before_implementation"] is True
    assert pathlib.Path(result["product_design_governance"]["paths"]["goal_fidelity_contract"]).is_file()


def test_every_governance_artifact_matches_schema_and_hash(tmp_path: pathlib.Path) -> None:
    product = _role_governance(tmp_path)
    for document in product["documents"].values():
        assert governance.validate_artifact(document) == {"status": "PASS", "errors": []}
    project = tmp_path / "project"
    project.mkdir()
    (project / "recognizer.py").write_text("dominant_hue = 'red'\n", encoding="utf-8")
    reports = governance.evaluate_and_write_project_reports(project, product, test_evidence={"status": "PASS"})
    for document in reports["reports"].values():
        assert governance.validate_artifact(document) == {"status": "PASS", "errors": []}
