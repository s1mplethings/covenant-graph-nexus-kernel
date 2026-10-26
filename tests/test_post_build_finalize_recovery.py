from __future__ import annotations

import json
import pathlib

import pytest

from scripts import codex_conversation
from scripts import provider_execution_metrics
from scripts import run_codex_conversation_generation
from scripts import run_local_pipeline_impl as pipeline


def _read(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("pipeline_blob_chars", "minimum_original", "maximum_original"),
    [
        (2_000, 0, 20_000),
        (38_000, 30_000, 60_000),
        (112_000, 100_000, 160_000),
    ],
)
def test_semantic_aggregate_is_bounded_and_preserves_source_artifact(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    pipeline_blob_chars: int,
    minimum_original: int,
    maximum_original: int,
) -> None:
    phase_log = tmp_path / "provider_phase_log.jsonl"
    captured: dict = {}

    def fake_provider_text(messages, *_args, **_kwargs):
        captured["prompt_chars"] = sum(len(str(item.get("content", ""))) for item in messages)
        return json.dumps(
            {
                "component": "cross_component",
                "verdict": "pass",
                "blockers": [],
                "integration_failures": [],
            }
        )

    monkeypatch.setattr(pipeline, "provider_text", fake_provider_text)
    result = pipeline.provider_semantic_cross_component_review(
        goal="Build a durable CLI and preserve exact totals.",
        files=[{"path": "main.py", "content": "print('ok')\n"}],
        component_reviews=[
            {"component": "backend", "verdict": "pass", "summary": "ok", "blockers": []}
        ],
        component_pipeline={
            "components": [
                {
                    "id": "backend",
                    "required_paths": ["main.py"],
                    "canonical_goal_spec": {
                        "constraints": ["no network"],
                        "acceptance_behaviors": ["exact totals"],
                    },
                    "historical_duplicate_context": "x" * pipeline_blob_chars,
                }
            ]
        },
        model="test-model",
        timeout=10,
        phase_log_path=phase_log,
        routing_policy=None,
    )

    receipt = _read(tmp_path / "artifacts" / "semantic_review" / "cross_component_compaction.json")
    source = _read(tmp_path / "artifacts" / "semantic_review" / "cross_component_source.json")
    assert result["verdict"] == "pass"
    assert minimum_original <= receipt["original_chars"] <= maximum_original
    assert captured["prompt_chars"] <= receipt["hard_prompt_chars"]
    assert source["component_pipeline"]["components"][0]["historical_duplicate_context"] == "x" * pipeline_blob_chars
    assert receipt["source_evidence_ref"].endswith("cross_component_source.json")
    assert "historical_duplicate_context" in receipt["projection_omissions"]["component_keys"]


def test_semantic_aggregate_exception_becomes_durable_failure(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    phase_log = tmp_path / "provider_phase_log.jsonl"

    def explode(**_kwargs):
        raise ValueError("aggregate exploded")

    monkeypatch.setattr(pipeline, "split_semantic_review_pipeline", explode)
    result = pipeline.provider_review_project(
        "goal",
        {},
        {},
        {},
        {},
        {"component_pipeline": {"components": [{"id": "backend"}]}},
        [{"path": f"backend/f{i}.py", "content": "x" * 10_000} for i in range(8)],
        "test-model",
        10,
        phase_log_path=phase_log,
    )

    events = [json.loads(line) for line in phase_log.read_text(encoding="utf-8").splitlines()]
    assert result["status"] == "fail"
    assert result["structured_blockers"][0]["kind"] == "semantic_aggregation_failed"
    assert events[-1]["event"] == "semantic_review_split_failed"
    assert events[-1]["retry_allowed"] is False


def test_nonplanning_provider_stage_projects_repeated_context(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict = {}

    def fake_provider_text(messages, *_args, **_kwargs):
        captured["prompt_chars"] = sum(len(str(item.get("content", ""))) for item in messages)
        return json.dumps({"summary": "bounded", "decisions": ["keep CLI"], "risks": []})

    monkeypatch.setattr(pipeline, "provider_text", fake_provider_text)
    result = pipeline.provider_stage_checkpoint(
        provider_mode="codex_surrogate",
        stage="interaction_design",
        context={
            "goal": "Build a local CLI",
            "selected_project_direction": {"id": "cli", "domain": "local", "blob": "x" * 30_000},
            "complexity_project_contract": {
                "required_paths": ["main.py", "DELIVERY_NOTES.md"],
                "duplicate_history": "y" * 40_000,
            },
        },
        run_dir=tmp_path,
        phase_log_path=tmp_path / "provider_phase_log.jsonl",
    )

    source_path = tmp_path / "artifacts" / "provider_stage_artifacts" / "interaction_design.source_context.json"
    assert result["payload"]["summary"] == "bounded"
    assert captured["prompt_chars"] < pipeline.semantic_review_budget_config()["hard_prompt_chars"]
    assert _read(source_path)["selected_project_direction"]["blob"] == "x" * 30_000
    assert "provider_stage_context_bounded" in (tmp_path / "provider_phase_log.jsonl").read_text(encoding="utf-8")


def _patch_candidate_finalize_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "candidate_visual_surface_required", lambda *_args: False)
    monkeypatch.setattr(
        pipeline.check_test_environment,
        "check_environment",
        lambda *_args, **_kwargs: {"status": "pass", "failures": [], "warnings": []},
    )
    monkeypatch.setattr(
        pipeline,
        "run_allowed_command",
        lambda argv, *_args, **_kwargs: {"status": "pass", "argv": argv, "returncode": 0},
    )
    monkeypatch.setattr(
        pipeline,
        "run_generated_project_fixture",
        lambda *_args, **_kwargs: {"status": "skipped", "receipt_path": "fixture.json", "blockers": []},
    )
    monkeypatch.setattr(
        pipeline,
        "run_project_usage_agent",
        lambda *_args, **_kwargs: {"status": "pass", "screenshots": [], "workflow_video": "", "events": []},
    )
    monkeypatch.setattr(pipeline, "candidate_direct_cli_leaf_contract_issues", lambda *_args: [])
    monkeypatch.setattr(pipeline, "candidate_build_coherence_issues", lambda *_args: [])
    monkeypatch.setattr(pipeline, "create_candidate_diagnostic_package", lambda _project, run: run / "diagnostic.zip")
    monkeypatch.setattr(pipeline, "validate_candidate_review_artifacts", lambda *_args: {"status": "pass", "issues": []})


def test_finalize_recovers_interruption_and_reuses_completed_result(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    run_dir = tmp_path / "run"
    project.mkdir()
    (project / "tests").mkdir()
    (project / "main.py").write_text("print('ok')\n", encoding="utf-8")
    checkpoint = run_dir / "artifacts" / "post_build_finalize_checkpoint.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(json.dumps({"status": "running", "attempt": 1}), encoding="utf-8")
    _patch_candidate_finalize_dependencies(monkeypatch)
    deadline = pipeline.ProgressDeadline(10**12, extension_seconds=30, phase_log_path=run_dir / "provider_phase_log.jsonl")

    first = pipeline.run_candidate_post_build_finalize(
        project_dir=project,
        run_dir=run_dir,
        user_goal="goal",
        generated_files=["main.py"],
        online_inputs={},
        example_outputs={},
        model="test-model",
        timeout=10,
        phase_log_path=run_dir / "provider_phase_log.jsonl",
        deadline=deadline,
        classifications={},
        component_pipeline={"components": [{"id": "backend"}]},
    )
    completed = _read(checkpoint)
    result_path = run_dir / "artifacts" / "candidate_post_build_finalize.json"
    first_mtime = result_path.stat().st_mtime_ns
    monkeypatch.setattr(
        pipeline.check_test_environment,
        "check_environment",
        lambda *_args, **_kwargs: pytest.fail("completed finalize must be reused"),
    )
    second = pipeline.run_candidate_post_build_finalize(
        project_dir=project,
        run_dir=run_dir,
        user_goal="goal",
        generated_files=["main.py"],
        online_inputs={},
        example_outputs={},
        model="test-model",
        timeout=10,
        phase_log_path=run_dir / "provider_phase_log.jsonl",
        deadline=deadline,
        classifications={},
        component_pipeline={"components": [{"id": "backend"}]},
    )

    assert first["status"] == "pass"
    assert second == first
    assert completed["status"] == "completed"
    assert completed["recovered_from_interruption"] is True
    assert result_path.stat().st_mtime_ns == first_mtime
    assert '"status": "reused"' in (run_dir / "provider_phase_log.jsonl").read_text(encoding="utf-8")


def test_provider_metrics_persist_retries_windows_share_violation(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    phase_log = tmp_path / "provider_phase_log.jsonl"
    key = provider_execution_metrics._key(phase_log)
    provider_execution_metrics._STATE.pop(key, None)
    original_replace = pathlib.Path.replace
    attempts = {"count": 0}

    def flaky_replace(source: pathlib.Path, target: pathlib.Path) -> pathlib.Path:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise PermissionError(5, "simulated Windows sharing violation")
        return original_replace(source, target)

    monkeypatch.setattr(pathlib.Path, "replace", flaky_replace)
    provider_execution_metrics.declare_jobs(phase_log, ["job-1"])

    receipt = tmp_path / "artifacts" / "provider_execution_metrics.json"
    assert json.loads(receipt.read_text(encoding="utf-8"))["provider_jobs_total"] == 1
    assert attempts["count"] == 2
    assert not list(receipt.parent.glob("provider_execution_metrics.json.*.tmp"))


def test_successful_formal_result_materializes_generated_project_once(tmp_path: pathlib.Path) -> None:
    source = tmp_path / "canonical"
    source.mkdir()
    manifest = {
        "run_id": "run-1",
        "candidate_id": "candidate-1",
        "candidate_hash": "sha256:candidate",
        "package_sha256": "sha256:package",
    }
    (source / "delivery_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (source / "main.py").write_text("print('ok')\n", encoding="utf-8")
    target = tmp_path / "agent-kit" / "generated-project"

    path, reused = run_codex_conversation_generation.materialize_generated_project(
        {"status": "PASS_WITH_LIMITS", "project_dir": str(source)}, str(target)
    )
    second_path, second_reused = run_codex_conversation_generation.materialize_generated_project(
        {"status": "PASS_WITH_LIMITS", "project_dir": str(source)}, str(target)
    )

    assert pathlib.Path(path) == target.resolve()
    assert reused is False
    assert second_path == path
    assert second_reused is True
    assert json.loads((target / "delivery_manifest.json").read_text(encoding="utf-8")) == manifest
    assert (target / "main.py").is_file()


def test_generation_cli_preserves_attempt_identity_argument() -> None:
    source = pathlib.Path(run_codex_conversation_generation.__file__).read_text(encoding="utf-8")
    assert 'parser.add_argument("--generation-attempt-id", default="")' in source

