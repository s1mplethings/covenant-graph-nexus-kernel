from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
LEGACY_PROJECT_PACK = ROOT / "project_management" / "cgkn" / "project_management.json"
requires_legacy_management = pytest.mark.skipif(not LEGACY_PROJECT_PACK.is_file(), reason="historical_asset: pre-current PMP self-hosting pack was retired")
sys.path.insert(0, str(ROOT / "src"))

from cgkn_project_management import (  # noqa: E402
    new_iteration,
    record_experience_usage,
    retrieve_experience,
    select_delivery_approach,
    validate_enterprise_experience_pack,
    validate_iteration,
    validate_project_management_pack,
)


def load_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_delivery_approach_is_tailored_from_uncertainty_and_criticality() -> None:
    assert select_delivery_approach(
        requirements_uncertainty="low",
        technical_uncertainty="low",
        criticality="low",
    )["delivery_approach"] == "predictive"
    assert select_delivery_approach(
        requirements_uncertainty="high",
        technical_uncertainty="medium",
        criticality="low",
    )["delivery_approach"] == "adaptive"
    assert select_delivery_approach(
        requirements_uncertainty="high",
        technical_uncertainty="medium",
        criticality="high",
    )["delivery_approach"] == "hybrid"


@pytest.mark.historical_asset
@requires_legacy_management
def test_cgkn_self_hosting_artifacts_pass_semantic_validation() -> None:
    project = load_json(ROOT / "project_management" / "cgkn" / "project_management.json")
    iteration = load_json(ROOT / "project_management" / "cgkn" / "iterations" / "ITER-001.json")
    experience = load_json(ROOT / "project_management" / "enterprise_experience.json")

    assert validate_project_management_pack(project)["status"] == "PASS"
    assert validate_iteration(iteration, project)["status"] == "PASS"
    assert validate_enterprise_experience_pack(experience)["status"] == "PASS"


@pytest.mark.historical_asset
@requires_legacy_management
def test_experience_retrieval_is_bounded_relevant_and_reviewed() -> None:
    experience = load_json(ROOT / "project_management" / "enterprise_experience.json")
    candidate = next(row for row in experience["items"] if row["id"] == "EXP-CGKN-BOOTSTRAP-001")
    candidate["experience_state"] = "candidate"
    candidate["evidence_refs"] = []
    result = retrieve_experience(experience, tags=["quality", "cgkn"], max_items=1)

    assert len(result["selected_items"]) == 1
    assert result["selected_items"][0]["id"] == "EXP-CGKN-QUALITY-001"
    assert result["selected_items"][0]["experience_state"] == "approved"
    assert all(row["id"] != "EXP-CGKN-BOOTSTRAP-001" for row in result["selected_items"])
    assert any(
        row["experience_id"] == "EXP-CGKN-BOOTSTRAP-001" and row["reason"] == "state:candidate"
        for row in result["excluded_items"]
    )


@pytest.mark.historical_asset
@requires_legacy_management
def test_experience_usage_records_outcome_without_promoting_state() -> None:
    experience = load_json(ROOT / "project_management" / "enterprise_experience.json")
    original = next(row for row in experience["items"] if row["id"] == "EXP-CGKN-QUALITY-001")
    updated = record_experience_usage(
        experience,
        experience_id="EXP-CGKN-QUALITY-001",
        project_id="cgkn",
        iteration_id="ITER-001",
        applied=True,
        outcome="successful",
        evidence_refs=["tests/result.json"],
    )
    item = next(row for row in updated["items"] if row["id"] == "EXP-CGKN-QUALITY-001")

    assert item["experience_state"] == "approved"
    assert item["usage_count"] == original["usage_count"] + 1
    assert item["successful_usage_count"] == original["successful_usage_count"] + 1
    assert updated["usage_receipts"][-1]["outcome"] == "successful"


@pytest.mark.historical_asset
@requires_legacy_management
def test_iteration_inherits_backlog_acceptance_and_quality_metrics() -> None:
    project = load_json(ROOT / "project_management" / "cgkn" / "project_management.json")
    iteration = new_iteration(
        project,
        iteration_id="ITER-002",
        goal="Integrate tailored management context.",
        backlog_item_ids=["PB-003"],
    )

    assert iteration["backlog_item_ids"] == ["PB-003"]
    assert iteration["acceptance_criteria"]
    assert {row["id"] for row in iteration["quality_metrics"]} == {"QM-INTEGRATION", "QM-REGRESSION"}
    assert validate_iteration(iteration, project)["status"] == "PASS"


def test_skill_helper_initializes_and_validates_a_project(tmp_path: pathlib.Path) -> None:
    helper = ROOT / "skills" / "manage-pmp-agile-quality" / "scripts" / "manage_project.py"
    target = tmp_path / "management"
    initialized = subprocess.run(
        [
            sys.executable,
            str(helper),
            "init",
            "--output",
            str(target),
            "--project-id",
            "sample",
            "--project-name",
            "Sample",
            "--goal",
            "Deliver a tested increment.",
            "--requirements-uncertainty",
            "high",
            "--technical-uncertainty",
            "medium",
            "--criticality",
            "high",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr
    assert load_json(target / "project_management.json")["delivery_approach"] == "hybrid"

    validated = subprocess.run(
        [sys.executable, str(helper), "validate", "--path", str(target / "project_management.json")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert validated.returncode == 0, validated.stdout + validated.stderr
    assert json.loads(validated.stdout)["status"] == "PASS"


@pytest.mark.historical_asset
@requires_legacy_management
def test_skill_helper_runs_iteration_lifecycle(tmp_path: pathlib.Path) -> None:
    helper = ROOT / "skills" / "manage-pmp-agile-quality" / "scripts" / "manage_project.py"
    project_path = tmp_path / "project_management.json"
    iteration_path = tmp_path / "iterations" / "ITER-099.json"
    project_path.write_text(
        (ROOT / "project_management" / "cgkn" / "project_management.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    started = subprocess.run(
        [
            sys.executable,
            str(helper),
            "start-iteration",
            "--project-pack",
            str(project_path),
            "--iteration-id",
            "ITER-099",
            "--goal",
            "Exercise the deterministic lifecycle.",
            "--backlog-item",
            "PB-003",
            "--output",
            str(iteration_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert started.returncode == 0, started.stdout + started.stderr
    assert load_json(iteration_path)["workflow_state"] == "active"

    closed = subprocess.run(
        [
            sys.executable,
            str(helper),
            "close-iteration",
            "--path",
            str(iteration_path),
            "--project-pack",
            str(project_path),
            "--evidence-status",
            "PASS",
            "--review-outcome",
            "accepted",
            "--evidence-ref",
            "tests/result.json",
            "--worked",
            "Bounded lifecycle commands remained deterministic.",
            "--experiment",
            "Measure first-pass acceptance on the next comparable iteration.",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert closed.returncode == 0, closed.stdout + closed.stderr
    assert load_json(iteration_path)["workflow_state"] == "closed"
    updated = load_json(project_path)
    assert next(row for row in updated["product_backlog"] if row["id"] == "PB-003")["state"] == "done"


def test_self_hosting_contract_and_skill_are_discoverable() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    skill = (ROOT / "skills" / "manage-pmp-agile-quality" / "SKILL.md").read_text(encoding="utf-8")
    registry = (ROOT / "docs" / "01_contract_registry.md").read_text(encoding="utf-8")

    assert "skills/manage-pmp-agile-quality" in agents
    assert "CGKNAdaptiveProjectManagementPack" in registry
    assert "local_packager" in skill
    assert "second generation route" in skill
