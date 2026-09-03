from __future__ import annotations

import pathlib
import sys

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import provider_jobs


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
