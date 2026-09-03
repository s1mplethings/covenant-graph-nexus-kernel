from __future__ import annotations

import pathlib
import sys
import threading
import time

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


def test_independent_provider_jobs_overlap_and_integration_waits() -> None:
    barrier = threading.Barrier(2)
    active = 0
    peak = 0
    lock = threading.Lock()
    started: dict[str, float] = {}

    jobs = [
        _job("frontend", "frontend.txt"),
        _job("backend", "backend.txt"),
        _job("integration", "contract.txt", ("frontend", "backend")),
    ]

    def worker(job: provider_jobs.ProviderJob, context: dict[str, str]) -> dict[str, str]:
        nonlocal active, peak
        started[job.id] = time.monotonic()
        if job.id in {"frontend", "backend"}:
            with lock:
                active += 1
                peak = max(peak, active)
            barrier.wait(timeout=2)
            time.sleep(0.03)
            with lock:
                active -= 1
        else:
            assert context["frontend.txt"] == "frontend"
            assert context["backend.txt"] == "backend"
        return {job.owns[0]: job.id}

    result = provider_jobs.execute_provider_jobs(jobs, worker, parallelism=2)

    assert result.status == "PASS"
    assert peak >= 2
    assert result.metrics["provider_peak_concurrency"] >= 2
    assert result.metrics["provider_api_call_count"] == 3
    assert started["integration"] > started["frontend"]
    assert started["integration"] > started["backend"]


def test_concurrency_cap_and_merge_are_deterministic() -> None:
    jobs = [_job("b", "b.txt"), _job("a", "a.txt"), _job("c", "c.txt")]

    def worker(job: provider_jobs.ProviderJob, _context: dict[str, str]) -> dict[str, str]:
        time.sleep(0.01)
        return {job.owns[0]: job.id}

    result = provider_jobs.execute_provider_jobs(jobs, worker, parallelism=1)
    assert result.metrics["provider_peak_concurrency"] == 1
    assert result.merge_order == ["a:a.txt", "b:b.txt", "c:c.txt"]


def test_ownership_conflict_and_foreign_patch_are_rejected() -> None:
    with pytest.raises(ValueError, match="ownership_conflict"):
        provider_jobs.execute_provider_jobs(
            [_job("a", "shared.json"), _job("b", "shared.json")],
            lambda job, context: {},
        )

    result = provider_jobs.execute_provider_jobs(
        [_job("a", "a.txt")],
        lambda job, context: {"foreign.txt": "bad"},
    )
    assert result.status == "NEEDS_REWORK"
    assert "patch_set.ownership" in result.jobs["a"].error


def test_dotfile_and_directory_ownership_are_preserved() -> None:
    job = _job("workflow", ".github/workflows/")
    result = provider_jobs.execute_provider_jobs(
        [job],
        lambda _job_value, _context: {".github/workflows/ci.yml": "name: ci\n"},
    )

    assert result.status == "PASS"
    assert result.files[".github/workflows/ci.yml"] == "name: ci\n"


def test_failed_leaf_only_retry_reuses_passed_jobs_without_codex() -> None:
    jobs = [_job("frontend", "frontend.txt"), _job("backend", "backend.txt")]
    first_calls: list[str] = []

    def first_worker(job: provider_jobs.ProviderJob, _context: dict[str, str]) -> dict[str, str]:
        first_calls.append(job.id)
        if job.id == "backend":
            raise RuntimeError("ordinary provider failure")
        return {job.owns[0]: "passed"}

    first = provider_jobs.execute_provider_jobs(jobs, first_worker, parallelism=2)
    second_calls: list[str] = []

    def repair_worker(job: provider_jobs.ProviderJob, _context: dict[str, str]) -> dict[str, str]:
        second_calls.append(job.id)
        return {job.owns[0]: "repaired"}

    second = provider_jobs.execute_provider_jobs(
        jobs,
        repair_worker,
        prior_results=first.jobs,
        retry_job_ids={"backend"},
        parallelism=2,
    )

    assert first.status == "NEEDS_REWORK"
    assert second.status == "PASS"
    assert second_calls == ["backend"]
    assert second.metrics["provider_jobs_reused_after_pass"] == 1
    assert second.metrics["provider_jobs_repaired"] == 1
    assert second.metrics["provider_api_call_count"] == 1
    assert "codex" not in provider_jobs.__dict__


def test_provider_exception_isolation_allows_independent_job_to_finish() -> None:
    jobs = [
        _job("fail", "fail.txt"),
        _job("pass", "pass.txt"),
        _job("blocked", "blocked.txt", ("fail",)),
    ]

    def worker(job: provider_jobs.ProviderJob, _context: dict[str, str]) -> dict[str, str]:
        if job.id == "fail":
            raise RuntimeError("boom")
        return {job.owns[0]: "ok"}

    result = provider_jobs.execute_provider_jobs(jobs, worker, parallelism=2)
    assert result.jobs["fail"].status == "FAIL"
    assert result.jobs["pass"].status == "PASS"
    assert result.jobs["blocked"].status == "BLOCKED"
    assert result.files["pass.txt"] == "ok"
