from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_commercial_readiness


def make_project(root: pathlib.Path) -> pathlib.Path:
    project = root / "candidate"
    project.mkdir()
    (project / "README.md").write_text("# commercial readiness project\n", encoding="utf-8")
    (project / "TEST_REPORT.md").write_text("commands_run:\n- npm test\n", encoding="utf-8")
    (project / "package.json").write_text("{}", encoding="utf-8")
    return project


def ok_config() -> dict:
    return {"providers": [{"name": "primary", "models": {"large": "large"}, "quota_required": False, "connectivity_report": "__missing_connectivity_report__.json"}]}


def quota_config() -> dict:
    return {"providers": [{"name": "primary", "models": {"large": "large"}, "quota_required": True}]}


def test_commercial_readiness_ready_when_all_pass(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = make_project(pathlib.Path(temp_dir))

        monkeypatch.setattr(run_commercial_readiness.check_test_environment, "check_environment", lambda candidate: {"status": "pass"})
        monkeypatch.setattr(run_commercial_readiness.product_acceptance, "evaluate_product_acceptance", lambda *args, **kwargs: {"status": "pass", "commercial_ready": True, "weak_features": [], "missing_core_features": []})
        monkeypatch.setattr(run_commercial_readiness.artifact_integrity, "scan_no_fake_pass", lambda root: {"status": "pass", "blockers": []})
        report = run_commercial_readiness.assess_commercial_readiness(
            provider_config=ok_config(),
            candidate_dir=project,
            run_live=False,
            run_pytest=False,
            formal_project_result={"status": "pass", "verdict": "PASS_FINAL"},
        )

    assert report["commercial_status"] == "COMMERCIAL_READY"


def test_commercial_readiness_beta_when_provider_quota_blocked(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = make_project(pathlib.Path(temp_dir))
        monkeypatch.setenv("CGNK_PROVIDER_PRIMARY_STATUS", "PROVIDER_QUOTA_EXCEEDED")
        monkeypatch.setattr(run_commercial_readiness.check_test_environment, "check_environment", lambda candidate: {"status": "pass"})
        monkeypatch.setattr(run_commercial_readiness.artifact_integrity, "scan_no_fake_pass", lambda root: {"status": "pass", "blockers": []})

        report = run_commercial_readiness.assess_commercial_readiness(provider_config=quota_config(), candidate_dir=project, run_live=False, run_pytest=False)

    assert report["commercial_status"] == "COMMERCIAL_BETA"
    assert report["provider"]["report_status"] == "COMMERCIAL_BETA_PROVIDER_BLOCKED"


def test_commercial_readiness_blocked_when_security_fails(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = make_project(pathlib.Path(temp_dir))
        (project / "package.json").write_text('{"scripts":{"postinstall":"rm -rf .."}}', encoding="utf-8")
        monkeypatch.setattr(run_commercial_readiness.check_test_environment, "check_environment", lambda candidate: {"status": "pass"})
        monkeypatch.setattr(run_commercial_readiness.artifact_integrity, "scan_no_fake_pass", lambda root: {"status": "pass", "blockers": []})

        report = run_commercial_readiness.assess_commercial_readiness(provider_config=ok_config(), candidate_dir=project, run_live=False, run_pytest=False)

    assert report["commercial_status"] == "COMMERCIAL_BLOCKED"
    assert "security_fail" in report["remaining_blockers"]


def test_commercial_readiness_blocked_when_fake_artifact_accepted(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = make_project(pathlib.Path(temp_dir))
        monkeypatch.setattr(run_commercial_readiness.check_test_environment, "check_environment", lambda candidate: {"status": "pass"})
        monkeypatch.setattr(run_commercial_readiness.artifact_integrity, "scan_no_fake_pass", lambda root: {"status": "fail", "blockers": ["fake"]})

        report = run_commercial_readiness.assess_commercial_readiness(provider_config=ok_config(), candidate_dir=project, run_live=False, run_pytest=False)

    assert report["commercial_status"] == "COMMERCIAL_BLOCKED"
    assert "fake_artifact_risk" in report["remaining_blockers"]


def test_commercial_readiness_beta_when_provider_quota_and_no_product_evidence(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir) / "empty_candidate"
        project.mkdir()
        monkeypatch.setenv("CGNK_PROVIDER_PRIMARY_STATUS", "PROVIDER_QUOTA_EXCEEDED")
        monkeypatch.setattr(run_commercial_readiness.check_test_environment, "check_environment", lambda candidate: {"status": "pass"})
        monkeypatch.setattr(run_commercial_readiness.artifact_integrity, "scan_no_fake_pass", lambda root: {"status": "pass", "blockers": []})

        report = run_commercial_readiness.assess_commercial_readiness(provider_config=quota_config(), candidate_dir=project, run_live=False, run_pytest=False)

    assert report["commercial_status"] == "COMMERCIAL_BETA"
    assert "provider_quota" in report["beta_reasons"]
    assert "no_product_evidence" in report["beta_reasons"]
    assert "product_acceptance_not_commercial_ready" not in report["beta_reasons"]
    assert report["product_acceptance"]["status"] == "not_evaluated"
    assert report["product_acceptance"]["reason"] == "NO_PRODUCT_EVIDENCE"
    assert report["customer_status"]["public_status"] == "WAITING_FOR_PROVIDER_QUOTA"
