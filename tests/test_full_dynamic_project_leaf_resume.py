from __future__ import annotations

import pathlib

import pytest

from scripts.full_dynamic_project_leaf_resume import _static_missing, run_leaf_resume
from scripts.full_dynamic_project_resume_analyzer import analyze_previous_run
from scripts.run_full_dynamic_real_project_eval import (
    controlled_backend_output,
    controlled_test_output,
)
from scripts.run_real_provider_frontend_branch_phase import controlled_frontend_output


ROOT = pathlib.Path(__file__).resolve().parents[1]
PREVIOUS = ROOT / "generated" / "full_dynamic_real_project_eval"
pytestmark = pytest.mark.e2e


def _overrides() -> dict[str, str]:
    return {
        "dashboard_page_leaf": controlled_frontend_output("dashboard_page_leaf"),
        "settings_page_leaf": controlled_frontend_output("settings_page_leaf"),
        "tasks_page_leaf": controlled_frontend_output("tasks_page_leaf"),
        "smoke_test_leaf": controlled_test_output("smoke_test_leaf"),
        "search_service_leaf": controlled_backend_output("search_service_leaf"),
    }


def test_leaf_resume_reuses_passes_and_only_executes_failed_leaves(tmp_path: pathlib.Path) -> None:
    _, plan, _ = analyze_previous_run(PREVIOUS, out_dir=tmp_path / "root")
    result = run_leaf_resume(
        resume_plan=plan,
        out_dir=tmp_path / "root" / "leaf_resume",
        project_dir=tmp_path / "project",
        readiness_override={"provider_ready": True},
        provider_output_overrides=_overrides(),
    )

    assert result["verdict"] == "PASS"
    assert len(result["reused"]) == 9
    assert all(item["provider_called"] is False for item in result["reused"])
    assert {item["leaf_id"] for item in result["resumed"]} == set(plan["resume_leaf"])
    assert result["repaired"][0]["leaf_id"] == "search_service_leaf"
    assert result["repaired"][0]["result"] == "PASS"
    assert result["replacements"] == []


def test_repeated_provider_unavailable_blocks_without_fake_files(tmp_path: pathlib.Path) -> None:
    _, plan, _ = analyze_previous_run(PREVIOUS, out_dir=tmp_path / "root")
    result = run_leaf_resume(
        resume_plan=plan,
        out_dir=tmp_path / "root" / "leaf_resume",
        project_dir=tmp_path / "project",
        readiness_override={"provider_ready": False},
    )

    assert result["classification"] == "provider_unavailable_during_resume"
    assert result["verdict"] == "BLOCKED"
    assert not (tmp_path / "project" / "app" / "templates" / "dashboard.html").exists()
    assert (tmp_path / "root" / "leaf_resume" / "pruning_events.jsonl").exists()


def test_retry_persisted_blocked_replacement_only(tmp_path: pathlib.Path) -> None:
    _, plan, _ = analyze_previous_run(PREVIOUS, out_dir=tmp_path / "root")
    plan["resume_leaf"] = []
    plan["repair_leaf"] = []
    plan["prune_candidates"] = []
    leaf_out = tmp_path / "root" / "leaf_resume"
    leaf_out.mkdir(parents=True)
    (leaf_out / "leaf_resume_result.json").write_text(
        """{
  "verdict": "BLOCKED",
  "classification": "provider_unavailable_during_resume",
  "reused": [],
  "resumed": [],
  "repaired": [],
  "replacements": [
    {
      "leaf_id": "backend_tests_leaf_v2",
      "replaces": "backend_tests_leaf",
      "parent_id": "test_branch_agent",
      "result": "BLOCKED",
      "classification": "provider_unavailable",
      "scope_contract": ["tests/test_backend_integration.py"]
    }
  ]
}
""",
        encoding="utf-8",
    )

    result = run_leaf_resume(
        resume_plan=plan,
        out_dir=leaf_out,
        project_dir=tmp_path / "project",
        readiness_override={"provider_ready": True},
        provider_output_overrides={
            "backend_tests_leaf_v2": controlled_test_output("backend_tests_leaf"),
        },
        retry_replacement_leaves=["backend_tests_leaf_v2"],
    )

    replacement = next(item for item in result["replacements"] if item["leaf_id"] == "backend_tests_leaf_v2")
    assert result["verdict"] == "PASS"
    assert replacement["result"] == "PASS"
    assert replacement["classification"] == "real_provider_leaf_pass"
    assert result["resumed"] == []
    assert result["repaired"] == []


def test_frontend_static_check_rejects_truncated_html(tmp_path: pathlib.Path) -> None:
    template = tmp_path / "app" / "templates" / "documents.html"
    template.parent.mkdir(parents=True)
    template.write_text("<!doctype html><html><head><title>documents import knowledge search tasks reports settings</title>", encoding="utf-8")

    missing = _static_missing(tmp_path, "documents_page_leaf")

    assert "html_structure:<body" in missing
    assert "html_structure:</html>" in missing
