from __future__ import annotations

import json
import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_reference_answer_project_trial as trial


REFERENCE_TEXT = """
The legacy reference project name is OLDREFX.
It was a local-first production-scale workbench with GUI, CLI, shared core logic,
unified pipeline stages, schema-bearing artifacts, delivery evidence, benchmark
summary, gap analysis, repair plan, and layered acceptance.
"""


def run_tmp_trial(tmp_path: pathlib.Path, *, capture_screenshot: bool = True) -> dict:
    return trial.run_trial(
        reference_answer=REFERENCE_TEXT,
        root=tmp_path,
        no_live=True,
        capture_screenshot=capture_screenshot,
        forbidden_terms=["OLDREFX"],
    )


def test_reference_trial_run_dirs_are_unique_under_parallel_allocation(tmp_path: pathlib.Path) -> None:
    artifacts = tmp_path / "artifacts"
    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(lambda _: trial.create_unique_run_dir(artifacts), range(16)))

    assert len({path.name for path in paths}) == 16
    assert all(path.exists() and path.is_dir() for path in paths)


def test_reference_trial_multi_sample_fixture_path_is_contract_only(tmp_path: pathlib.Path) -> None:
    result = trial.run_trial(
        reference_answer=REFERENCE_TEXT,
        root=tmp_path,
        no_live=True,
        capture_screenshot=True,
        forbidden_terms=["OLDREFX"],
        use_user_media_fixture=True,
        use_media_decode_smoke=True,
        use_real_asr_contract_fixture=True,
        use_asr_quality_gate_fixture=True,
        use_real_asr_multi_sample_eval_fixture=True,
    )

    capability = result["capability_manifest"]
    assert result["score"]["verdict"] == "PASS"
    assert result["name_leak_scan"]["status"] == "PASS"
    assert capability["asr_quality_status"] == "contract_only"
    assert capability["asr_evidence_tier"] == "contract_fixture"
    assert capability["asr_production_candidate"] is False
    assert result["commercial_readiness"]["commercial_ready"] is False


def test_reference_trial_promotion_fixture_refuses_candidate(tmp_path: pathlib.Path) -> None:
    result = trial.run_trial(
        reference_answer=REFERENCE_TEXT,
        root=tmp_path,
        no_live=True,
        capture_screenshot=True,
        forbidden_terms=["OLDREFX"],
        use_user_media_fixture=True,
        use_media_decode_smoke=True,
        use_real_asr_contract_fixture=True,
        use_asr_quality_gate_fixture=True,
        use_real_asr_multi_sample_eval_fixture=True,
        use_commercial_promotion_gate_fixture=True,
    )

    assert result["score"]["verdict"] == "PASS"
    assert result["name_leak_scan"]["status"] == "PASS"
    assert result["commercial_readiness"]["status"] == "COMMERCIAL_BETA_PLUS"
    assert result["commercial_readiness"]["commercial_ready"] is False
    assert result["capability_manifest"]["commercial_promotion_decision"] == "COMMERCIAL_BETA_PLUS"


def test_reference_trial_ready_fixture_remains_not_ready(tmp_path: pathlib.Path) -> None:
    result = trial.run_trial(
        reference_answer=REFERENCE_TEXT,
        root=tmp_path,
        no_live=True,
        capture_screenshot=True,
        forbidden_terms=["OLDREFX"],
        use_user_media_fixture=True,
        use_media_decode_smoke=True,
        use_real_asr_contract_fixture=True,
        use_asr_quality_gate_fixture=True,
        use_real_asr_multi_sample_eval_fixture=True,
        use_commercial_promotion_gate_fixture=True,
        use_commercial_ready_gate_fixture=True,
    )

    assert result["score"]["verdict"] == "PASS"
    assert result["name_leak_scan"]["status"] == "PASS"
    assert result["commercial_readiness"]["status"] == "COMMERCIAL_BETA_PLUS"
    assert result["commercial_readiness"]["ready_decision"] == "NOT_READY"
    assert result["commercial_readiness"]["commercial_ready"] is False
    assert result["capability_manifest"]["commercial_ready_decision"] == "NOT_READY"


def test_runner_accepts_reference_answer_and_generates_reference_profile(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)

    profile = result["reference_profile"]
    assert profile["profile_id"] == "reference_grade_project_trial_profile"
    assert profile["complexity_level"] == "production_scale"
    assert "local_first" in profile["required_capabilities"]
    assert profile["forbidden_reference_token_count"] >= 1
    assert "OLDREFX" not in json.dumps(profile)


def test_reference_profile_name_is_not_formal_project_output(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)

    project_dir = pathlib.Path(result["generated_project_path"])
    assert project_dir.name == "local_media_operations_workspace"
    assert "OLDREFX" not in project_dir.as_posix()
    assert "OLDREFX" not in (project_dir / "README.md").read_text(encoding="utf-8")
    assert result["name_leak_scan"]["status"] == "PASS"


def test_generated_project_contains_requirement_decision_artifacts(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    req_dir = pathlib.Path(result["run_dir"]) / "requirement_decision"

    for name in trial.REQUIREMENT_ARTIFACTS:
        assert (req_dir / name).exists(), name
    selected = json.loads((req_dir / "selected_requirement.json").read_text(encoding="utf-8"))
    assert selected["selected_requirement_id"]
    assert selected["mvp_scope"]
    assert selected["non_goals"]


def test_generated_project_contains_product_contract_docs(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    project_dir = pathlib.Path(result["generated_project_path"])

    for name in trial.PRODUCT_DOCS:
        path = project_dir / name
        assert path.exists(), name
        text = path.read_text(encoding="utf-8").lower()
        assert "selected_requirement.json" in text or "acceptance_contract.json" in text


def test_generated_project_contains_implementation_structure(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    project_dir = pathlib.Path(result["generated_project_path"])

    for name in ("orchestrator.py", "stages.py", "cli.py", "gui_app.py"):
        assert (project_dir / name).exists(), name
    assert "orchestrator" in (project_dir / "cli.py").read_text(encoding="utf-8")
    assert "orchestrator" in (project_dir / "gui_app.py").read_text(encoding="utf-8")
    assert result["layered_status"]["implementation_status"] == "PASS"


def test_generated_project_contains_delivery_evidence(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    project_dir = pathlib.Path(result["generated_project_path"])

    for name in trial.DELIVERY_FILES:
        assert (project_dir / name).exists(), name
    screenshot = pathlib.Path(result["artifact_integrity"]["screenshot_path"])
    assert screenshot.exists()
    assert result["delivery"]["smoke_command"]["status"] == "PASS"
    assert result["layered_status"]["delivery_status"] == "PASS"


def test_missing_screenshot_blocks_delivery_pass(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path, capture_screenshot=False)

    assert result["delivery"]["status"] == "PARTIAL"
    assert result["layered_status"]["delivery_status"] != "PASS"
    assert "screenshot_missing" in result["known_gaps"]


def test_missing_zip_blocks_delivery_pass(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    project_dir = pathlib.Path(result["generated_project_path"])
    (project_dir / "final_project_bundle.zip").unlink()

    artifact = trial.evaluate_artifact_integrity(project_dir, pathlib.Path(result["run_dir"]))
    layers = trial.requirement_acceptance_check.evaluate_layers(project_dir=project_dir, run_dir=pathlib.Path(result["run_dir"]))
    assert artifact["status"] == "FAIL"
    assert "final_project_bundle.zip_missing" in artifact["blockers"]
    assert layers["delivery_status"] != "PASS"


def test_delivery_pass_does_not_auto_mark_commercial_pass(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)

    assert result["layered_status"]["delivery_status"] == "PASS"
    assert result["commercial_readiness"]["status"] == "COMMERCIAL_BETA"
    assert result["commercial_readiness"]["commercial_ready"] is False


def test_score_contains_reference_profile_alignment(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)

    assert "reference_profile_alignment" in result["score"]["parts"]
    assert result["reference_profile_alignment"]["score"] >= 90
    assert result["reference_profile_alignment"]["status"] == "PASS"


def test_reference_name_leak_forces_trial_fail(tmp_path: pathlib.Path) -> None:
    result = run_tmp_trial(tmp_path)
    project_dir = pathlib.Path(result["generated_project_path"])
    (project_dir / "leaky_report.md").write_text("OLDREFX should not be here\n", encoding="utf-8")

    leak = trial.scan_name_leaks([project_dir], ["OLDREFX"])
    rescored = trial.score_trial(
        requirement={"status": "PASS", "paths": result["requirement_decision"]["paths"]},
        layered={
            "product_contract_status": "PASS",
            "implementation_status": "PASS",
            "delivery_status": "PASS",
        },
        artifact_integrity={"status": "PASS", "stage_artifact_schema": {"status": "PASS"}},
        reference_alignment={"score": 100},
        commercial={"honesty_status": "PASS"},
        leak_scan=leak,
    )

    assert leak["status"] == "FAIL"
    assert rescored["verdict"] == "FAIL"
    assert rescored["total"] == 0
