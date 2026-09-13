from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from scripts import provider_free_partial_acceptance_replay as replay


@pytest.fixture(scope="module")
def provider_free_report(tmp_path_factory: pytest.TempPathFactory) -> tuple[pathlib.Path, dict]:
    output = tmp_path_factory.mktemp("provider-free-report")
    report = replay.run(output)
    return output, report


def test_all_eight_deterministic_scenarios_pass(provider_free_report) -> None:
    _, report = provider_free_report
    assert len(report["scenarios"]) == 8
    assert all(item["passed"] for item in report["scenarios"].values())
    assert report["final_verdict"]["verdict"] == "PROVIDER_FREE_LOGIC_PASS"
    assert report["final_verdict"]["live_product_repair_verified"] is False
    assert report["final_verdict"]["live_provider_repeatability_verified"] is False
    assert report["final_verdict"]["provider_rerun_still_required"] is True


def test_case01_executes_real_csv_clean_preview_and_export(provider_free_report) -> None:
    _, report = provider_free_report
    case = report["cases"]["CASE01"]
    assert case["issues_fixed_by_first_repair"] >= 2
    assert case["actual_behavior"]["csv_upload"] == "PASS"
    assert case["actual_behavior"]["csv_clean"] == "PASS"
    assert case["actual_behavior"]["preview"] == "PASS"
    assert case["actual_behavior"]["export"] == "PASS"
    assert case["actual_behavior"]["delivery"] == "FAIL"
    assert case["full_case_pass"] is False
    assert case["final_candidate_not_v0"] is True
    assert case["rejected_v3_not_selected"] is True


def test_case03_executes_crud_move_persistence_export_and_startup_guard(provider_free_report) -> None:
    _, report = provider_free_report
    case = report["cases"]["CASE03"]
    assert case["candidate_materialized"] is True
    assert case["actual_behavior"]["startup"] == "PASS"
    assert case["actual_behavior"]["crud"] == "PASS"
    assert case["actual_behavior"]["persistence"] == "PASS"
    assert case["actual_behavior"]["export"] == "PASS"
    assert case["actual_behavior"]["move"] == "FAIL"
    assert case["persistence_export_improved"] is True
    assert case["startup_new_blocker_rejected"] is True


def test_partial_acceptance_new_blocker_and_schema_limits(provider_free_report) -> None:
    _, report = provider_free_report
    assert report["scenarios"]["A_partial_improvement"]["actual"] == "ACCEPT_PARTIAL_IMPROVEMENT"
    assert report["scenarios"]["B_no_target_improvement"]["actual"] == "REJECT_NO_TARGET_ISSUE_IMPROVEMENT"
    assert report["scenarios"]["C_new_blocker"]["actual"] == "REJECT_NEW_BLOCKER"
    assert report["scenarios"]["D_invalid_json_one_repair"]["schema_repair_attempts"] == 1
    assert report["scenarios"]["E_continuous_invalid_json"]["schema_repair_attempts"] == 1
    assert report["scenarios"]["F_candidate_not_materialized"]["score"] is None
    assert report["scenarios"]["G_score_down_issue_improved"]["passed"] is True
    assert report["partial_acceptance"]["case_score_required"] is False
    assert report["partial_acceptance"]["accepted_without_target_issue_improvement"] == 0


def test_accounting_lineage_and_single_scheduler_are_consistent(provider_free_report) -> None:
    output, report = provider_free_report
    accounting = json.loads((output / "repair_call_accounting.json").read_text(encoding="utf-8"))
    network = json.loads((output / "network_call_guard_report.json").read_text(encoding="utf-8"))
    lineage = json.loads((output / "candidate_lineage.json").read_text(encoding="utf-8"))
    assert report["accounting_consistent"] is True
    assert len(accounting["rows"]) == network["replay_transport_calls"]
    assert network["real_network_calls"] == 0
    assert network["provider_api_quota_consumed"] is False
    assert report["assertions"]["provider_schedulers_one"] is True
    assert report["assertions"]["component_wide_rollback_zero"] is True
    assert report["assertions"]["generic_scope_calls_zero"] is True
    assert lineage["case01"]["candidate_versions_total"] == 3
    assert lineage["case01"]["latest_candidate_id"] == report["cases"]["CASE01"]["final_candidate_id"]


def test_payload_manifest_and_required_artifacts_are_auditable(provider_free_report) -> None:
    output, _ = provider_free_report
    required = {
        "provider_free_logic_report.json",
        "replay_payload_manifest.json",
        "repair_call_accounting.json",
        "acceptance_history.json",
        "candidate_lineage.json",
        "network_call_guard_report.json",
        "final_verdict.json",
    }
    assert required <= {path.name for path in output.iterdir() if path.is_file()}
    manifest = json.loads((output / "replay_payload_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["payloads"]) == 11
    for row in manifest["payloads"]:
        assert row["replay_id"]
        assert row["purpose"]
        assert row["expected_result"]
        assert row["response_sha256"] == hashlib.sha256(
            row["response_text"].encode("utf-8")
        ).hexdigest()


def test_frozen_contract_partial_improvement_acceptance(provider_free_report) -> None:
    """FROZEN CONTRACT: verified target-issue improvement survives a failing case score."""
    _, report = provider_free_report
    assert report["scenarios"]["A_partial_improvement"]["actual"] == "ACCEPT_PARTIAL_IMPROVEMENT"
    assert report["scenarios"]["G_score_down_issue_improved"]["actual"] == "ACCEPT_PARTIAL_IMPROVEMENT"
    assert report["partial_acceptance"]["case_score_required"] is False


def test_frozen_contract_reject_no_target_issue_improvement(provider_free_report) -> None:
    """FROZEN CONTRACT: score movement cannot substitute for target-issue improvement."""
    _, report = provider_free_report
    assert report["scenarios"]["B_no_target_improvement"]["actual"] == (
        "REJECT_NO_TARGET_ISSUE_IMPROVEMENT"
    )
    assert report["partial_acceptance"]["accepted_without_target_issue_improvement"] == 0


def test_frozen_contract_reject_new_blocker(provider_free_report) -> None:
    """FROZEN CONTRACT: a newly introduced blocker always rejects the prospective candidate."""
    _, report = provider_free_report
    assert report["scenarios"]["C_new_blocker"]["actual"] == "REJECT_NEW_BLOCKER"
    assert report["cases"]["CASE03"]["startup_new_blocker_rejected"] is True


def test_frozen_contract_schema_repair_only_once(provider_free_report) -> None:
    """FROZEN CONTRACT: malformed Provider payloads receive at most one schema-repair call."""
    _, report = provider_free_report
    assert report["schema_repair_limit"] == 1
    assert report["scenarios"]["D_invalid_json_one_repair"]["schema_repair_attempts"] == 1
    assert report["scenarios"]["E_continuous_invalid_json"]["schema_repair_attempts"] == 1


def test_frozen_contract_candidate_materialization_failure(provider_free_report) -> None:
    """FROZEN CONTRACT: an unmaterialized candidate is never accepted or assigned a score."""
    _, report = provider_free_report
    scenario = report["scenarios"]["F_candidate_not_materialized"]
    assert scenario["actual"] == "CANDIDATE_MATERIALIZED_FALSE"
    assert scenario["candidate_materialized"] is False
    assert scenario["score"] is None
    assert report["assertions"]["unmaterialized_candidate_not_accepted"] is True


def test_frozen_contract_rejected_candidate_cannot_replace_accepted_candidate(
    provider_free_report,
) -> None:
    """FROZEN CONTRACT: a rejected later candidate cannot override the accepted lineage tip."""
    _, report = provider_free_report
    scenario = report["scenarios"]["H_multi_round_candidate_selection"]
    assert scenario["actual"] == "FINAL_CANDIDATE_V2"
    assert scenario["selected_candidate_id"] == scenario["v2_candidate_id"]
    assert report["cases"]["CASE01"]["rejected_v3_not_selected"] is True


def test_frozen_contract_final_candidate_does_not_regress_to_v0(provider_free_report) -> None:
    """FROZEN CONTRACT: accepted partial progress remains the final lineage tip, never V0."""
    _, report = provider_free_report
    for case in report["cases"].values():
        assert case["final_candidate_id"] != case["v0_candidate_id"]
    assert report["assertions"]["final_candidate_not_v0"] is True


def test_frozen_contract_accounting_rows_equal_actual_calls(provider_free_report) -> None:
    """FROZEN CONTRACT: each deterministic transport invocation has exactly one accounting row."""
    output, report = provider_free_report
    accounting = json.loads((output / "repair_call_accounting.json").read_text(encoding="utf-8"))
    network = json.loads((output / "network_call_guard_report.json").read_text(encoding="utf-8"))
    assert len(accounting["rows"]) == network["replay_transport_calls"]
    assert report["accounting_consistent"] is True


def test_frozen_contract_provider_scheduler_count_equals_one(provider_free_report) -> None:
    """FROZEN CONTRACT: repair reuses the sole production split-file ProviderJob executor."""
    _, report = provider_free_report
    assert report["orchestration_metrics"]["provider_schedulers"] == 1
    assert report["assertions"]["provider_schedulers_one"] is True


def test_frozen_contract_real_network_calls_equal_zero(provider_free_report) -> None:
    """FROZEN CONTRACT: deterministic replay must fail closed before any real network call."""
    output, report = provider_free_report
    network = json.loads((output / "network_call_guard_report.json").read_text(encoding="utf-8"))
    assert network["real_network_calls"] == 0
    assert network["provider_api_quota_consumed"] is False
    assert report["final_verdict"]["external_provider_calls"] == 0
