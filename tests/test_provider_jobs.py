from __future__ import annotations

import json
import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import provider_jobs
import run_local_pipeline_impl


def _job(job_id: str, owns: str, depends_on: tuple[str, ...] = ()) -> provider_jobs.ProviderJob:
    return provider_jobs.ProviderJob(
        id=job_id,
        goal=f"build {job_id}",
        depends_on=depends_on,
        owns=(owns,),
        acceptance=(f"{owns} is complete",),
    )


def test_provider_job_graph_contract_accepts_dependencies() -> None:
    jobs = [
        _job("frontend", "frontend.txt"),
        _job("backend", "backend.txt"),
        _job("integration", "contract.txt", ("frontend", "backend")),
    ]
    assert provider_jobs.validate_jobs(jobs) == []
    assert jobs[-1].depends_on == ("frontend", "backend")


def test_ownership_conflict_and_foreign_patch_are_rejected() -> None:
    errors = provider_jobs.validate_jobs(
        [_job("a", "shared.json"), _job("b", "shared.json")]
    )
    assert any("ownership_conflict" in error for error in errors)
    with pytest.raises(ValueError, match="patch_set.ownership"):
        provider_jobs.validate_patch_set(_job("a", "a.txt"), {"foreign.txt": "bad"})


def test_dotfile_and_directory_ownership_are_preserved() -> None:
    job = _job("workflow", ".github/workflows/")
    patch = provider_jobs.validate_patch_set(
        job, {".github/workflows/ci.yml": "name: ci\n"}
    )
    assert patch.files[".github/workflows/ci.yml"] == "name: ci\n"


def test_leaf_graph_maps_to_pure_provider_job_contract() -> None:
    graph = {
        "leaves": [
            {"leaf_id": "a", "path": "src/a.py", "purpose": "A", "depends_on": []},
            {"leaf_id": "b", "path": "src/b.py", "purpose": "B", "depends_on": ["src/a.py"]},
        ]
    }
    jobs = provider_jobs.provider_jobs_from_leaf_graph("backend", graph)
    assert [job.id for job in jobs] == ["a", "b"]
    assert jobs[1].depends_on == ("a",)
    assert provider_jobs.validate_jobs(jobs) == []


def test_provider_job_module_has_no_scheduler_authority() -> None:
    source = (SCRIPTS / "provider_jobs.py").read_text(encoding="utf-8")
    production = (SCRIPTS / "run_local_pipeline_impl.py").read_text(encoding="utf-8")
    assert "def execute_provider_jobs(" not in source
    assert "ThreadPoolExecutor" not in source
    assert "ThreadPoolExecutor" in production
    assert "provider_jobs.validate_patch_set" in production


def test_supervision_provider_repair_maps_exact_leaf_id_to_one_file(tmp_path: pathlib.Path) -> None:
    artifacts = tmp_path / "artifacts"
    components = artifacts / "provider_components"
    (components / "leaf_work_graphs").mkdir(parents=True)
    (artifacts / "generation_plan_checkpoint.json").write_text(
        json.dumps(
            {
                "plan_doc": {
                    "pipeline_plan": {
                        "payload": {
                            "component_pipeline": {
                                "components": [
                                    {
                                        "id": "backend",
                                        "purpose": "backend",
                                        "depends_on": [],
                                        "required_paths": ["src/a.py", "src/b.py"],
                                        "acceptance": [],
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (components / "backend_files.json").write_text(
        json.dumps(
            {
                "component_id": "backend",
                "files": [
                    {"path": "src/a.py", "content": "A = 1\n"},
                    {"path": "src/b.py", "content": "B = 1\n"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (components / "leaf_work_graphs" / "backend.json").write_text(
        json.dumps(
            {
                "component_id": "backend",
                "leaves": [
                    {"leaf_id": "backend:a", "path": "src/a.py"},
                    {"leaf_id": "backend:b", "path": "src/b.py"},
                ],
            }
        ),
        encoding="utf-8",
    )
    receipt = run_local_pipeline_impl.prepare_supervision_provider_repair(
        tmp_path,
        {
            "checkpoint_id": "checkpoint-1",
            "result_sha256": "a" * 64,
            "scope": "project",
            "summary": "A is inconsistent",
            "diagnosis": ["Repair only A"],
            "guidance": [],
            "repair_targets": ["backend:a"],
            "acceptance_checks": ["A passes"],
        },
        user_goal="build a backend",
    )
    pending = json.loads(
        (artifacts / "pending_repair_plan.json").read_text(encoding="utf-8")
    )
    assert receipt["affected_components"] == ["backend"]
    assert receipt["affected_files"] == ["src/a.py"]
    assert [action["path"] for action in pending["provider_actions"]] == ["src/a.py"]
