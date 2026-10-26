from __future__ import annotations

import json
import pathlib
import sys
import time

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
AGENT_SRC = ROOT / "tools" / "cgkn-agent-kit" / "src"
if str(AGENT_SRC) not in sys.path:
    sys.path.insert(0, str(AGENT_SRC))

from cgkn_agent_kit import core


class StartedProcess:
    pid = 4242

    def __init__(self, command, **_kwargs):
        state_path = pathlib.Path(command[command.index("--generation-job-state") + 1])
        job_id = command[command.index("--generation-job-id") + 1]
        current = core.read_json(state_path)
        core.write_json(state_path, {
            **current,
            "job_id": job_id,
            "run_id": "production-managed-1",
            "run_dir": str(state_path.parent / "runs" / "production-managed-1"),
            "state": "RUNNING",
            "process_id": self.pid,
        })


def start(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        core,
        "_process_liveness",
        lambda pid: {"pid": int(pid), "status": "ALIVE" if int(pid) == 4242 else "DEAD", "alive": int(pid) == 4242, "method": "test", "error_code": 0},
    )
    before = time.perf_counter()
    result = core.start_generation_job(
        [sys.executable, "canonical-worker.py"],
        cgkn_root=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        start_timeout=0.2,
        popen_factory=StartedProcess,
    )
    return result, time.perf_counter() - before


def test_l01_start_returns_before_provider_completion(tmp_path, monkeypatch):
    job, elapsed = start(tmp_path, monkeypatch)
    assert elapsed < 0.5
    assert job["state"] == "RUNNING"
    assert job["run_id"] == "production-managed-1"


def test_l02_request_completion_does_not_cancel_job(tmp_path, monkeypatch):
    job, _ = start(tmp_path, monkeypatch)
    observed = core.generation_job_status(tmp_path / "artifacts")
    assert observed["job_alive"] is True
    assert observed["job_id"] == job["job_id"]


def test_l03_simulated_client_disconnect_leaves_worker_running(tmp_path, monkeypatch):
    start(tmp_path, monkeypatch)
    assert core.generation_job_status(tmp_path / "artifacts")["state"] == "RUNNING"


def test_l04_status_read_does_not_start_provider_or_change_state(tmp_path, monkeypatch):
    start(tmp_path, monkeypatch)
    path = core.generation_job_path(tmp_path / "artifacts")
    before = path.read_bytes()
    core.generation_job_status(tmp_path / "artifacts")
    assert path.read_bytes() == before


def test_l05_second_start_deduplicates_live_worker(tmp_path, monkeypatch):
    first, _ = start(tmp_path, monkeypatch)

    def duplicate_forbidden(*_args, **_kwargs):
        pytest.fail("a second worker must not start")

    second = core.start_generation_job(
        [sys.executable, "canonical-worker.py"],
        cgkn_root=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        start_timeout=0,
        popen_factory=duplicate_forbidden,
    )
    assert second["deduplicated"] is True
    assert second["job_id"] == first["job_id"]


def write_job(tmp_path: pathlib.Path, **overrides):
    artifact_dir = tmp_path / "artifacts"
    run_dir = artifact_dir / "runs" / "production-managed-1"
    job_id = "generation-job-1"
    attempt_id = "generation-attempt-1"
    result_path = artifact_dir / f"generation_result.{job_id}.{attempt_id}.json"
    value = {
        "kind": "CGKNGenerationJob",
        "schema_version": "1.0",
        "job_id": job_id,
        "attempt_id": attempt_id,
        "run_id": "production-managed-1",
        "run_dir": str(run_dir),
        "result_path": str(result_path),
        "process_id": 4242,
        "state": "RUNNING",
        "terminal_reason": "",
        **overrides,
    }
    core.write_json(core.generation_job_path(artifact_dir), value)
    return artifact_dir, run_dir, result_path


def test_l06_running_job_reaches_terminal_success(tmp_path, monkeypatch):
    artifact_dir, _run_dir, result_path = write_job(tmp_path, state="COMPLETE", process_id=0)
    core.write_json(result_path, {
        "generation_job_id": "generation-job-1",
        "generation_attempt_id": "generation-attempt-1",
        "run_id": "production-managed-1",
        "candidate_hash": "sha256:candidate",
        "formal_evidence_status": "PASS",
        "resume": {"safe": True},
    })
    monkeypatch.setattr(core, "_process_alive", lambda _pid: False)
    status = core.generation_job_status(artifact_dir)
    assert status["state"] == "COMPLETE"
    assert status["candidate_present"] is True
    assert status["resume_safe"] is True


def test_l07_bounded_retry_failure_is_terminal(tmp_path, monkeypatch):
    artifact_dir, _run_dir, _result = write_job(tmp_path, state="REWORK_BLOCKED", process_id=0, terminal_reason="PROVIDER_TRANSPORT_TIMEOUT")
    monkeypatch.setattr(core, "_process_alive", lambda _pid: False)
    assert core.generation_job_status(artifact_dir)["state"] == "REWORK_BLOCKED"


def test_l08_worker_crash_is_safely_observable(tmp_path, monkeypatch):
    artifact_dir, _run_dir, _result = write_job(tmp_path)
    monkeypatch.setattr(core, "_process_alive", lambda _pid: False)
    status = core.generation_job_status(artifact_dir)
    assert status["state"] == "FAILED"
    assert status["terminal_reason"] == "WORKER_PROCESS_NOT_ALIVE"


def test_l09_explicit_cancellation_differs_from_disconnect(tmp_path, monkeypatch):
    artifact_dir, _run_dir, _result = write_job(tmp_path, state="CANCELLED", process_id=0, terminal_reason="EXPLICIT_CANCELLATION")
    monkeypatch.setattr(core, "_process_alive", lambda _pid: False)
    status = core.generation_job_status(artifact_dir)
    assert status["state"] == "CANCELLED"
    assert status["terminal_reason"] == "EXPLICIT_CANCELLATION"


def test_l10_terminal_failure_remains_eligible_for_fresh_revalidation():
    scripts = ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import codex_conversation
    assert codex_conversation.formal_generation_requires_new_run("REWORK_BLOCKED") is True
    assert codex_conversation.formal_generation_requires_new_run("RUNNING") is False


@pytest.mark.parametrize(
    ("count", "timeouts", "successes"),
    [(0, 0, 0), (1, 1, 0), (2, 1, 1)],
)
def test_m01_m03_status_projects_canonical_metrics(tmp_path, monkeypatch, count, timeouts, successes):
    artifact_dir, run_dir, _result = write_job(tmp_path, provider_attempts_completed=count, provider_timeouts=timeouts, provider_successes=successes)
    core.write_json(run_dir / "artifacts" / "provider_execution_metrics.json", {"provider_api_call_count": count})
    monkeypatch.setattr(core, "_process_alive", lambda _pid: True)
    status = core.generation_job_status(artifact_dir)
    assert status["provider_attempts_started"] == count
    assert status["provider_attempts_completed"] == count
    assert status["provider_timeouts"] == timeouts
    assert status["provider_successes"] == successes


def test_m04_polling_does_not_increment_metrics(tmp_path, monkeypatch):
    artifact_dir, run_dir, _result = write_job(tmp_path, provider_attempts_completed=2)
    metrics_path = run_dir / "artifacts" / "provider_execution_metrics.json"
    core.write_json(metrics_path, {"provider_api_call_count": 2})
    monkeypatch.setattr(core, "_process_alive", lambda _pid: True)
    before = metrics_path.read_bytes()
    for _ in range(3):
        assert core.generation_job_status(artifact_dir)["provider_attempts_started"] == 2
    assert metrics_path.read_bytes() == before


def test_m05_fixture_status_has_zero_live_calls(tmp_path, monkeypatch):
    artifact_dir, run_dir, _result = write_job(tmp_path, provider_attempts_completed=0)
    core.write_json(run_dir / "artifacts" / "provider_execution_metrics.json", {"provider_api_call_count": 0})
    monkeypatch.setattr(core, "_process_alive", lambda _pid: True)
    assert core.generation_job_status(artifact_dir)["provider_attempts_started"] == 0


def test_m06_outer_projection_equals_run_local_metrics(tmp_path, monkeypatch):
    artifact_dir, run_dir, _result = write_job(tmp_path)
    core.write_json(run_dir / "artifacts" / "provider_execution_metrics.json", {"provider_api_call_count": 6})
    monkeypatch.setattr(core, "_process_alive", lambda _pid: True)
    assert core.generation_job_status(artifact_dir)["provider_attempts_started"] == 6


class CapturedResumeProcess:
    pid = 5252
    command: list[str] = []

    def __init__(self, command, **_kwargs):
        type(self).command = list(command)


class SurrogateReport:
    def __init__(self, *, responded: bool, consumed: bool):
        self.responded = responded
        self.consumed = consumed

    def status(self, _run_dir):
        return {
            "requests": [
                {
                    "job_id": "provider-job-2",
                    "attempt_id": "attempt-2",
                    "responded": self.responded,
                    "consumed": self.consumed,
                }
            ]
        }


def _external_wait_job(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    artifact_dir, run_dir, _ = write_job(
        tmp_path,
        state="WAITING_REQUIREMENT_REPLAN",
        terminal_reason="WAITING_REQUIREMENT_REPLAN",
        process_id=4242,
    )
    run_dir.mkdir(parents=True)
    return artifact_dir, run_dir


def test_fsv_001_replan_response_resumes_same_run(tmp_path, monkeypatch):
    artifact_dir, run_dir = _external_wait_job(tmp_path)
    monkeypatch.setattr(core, "_load_surrogate_adapter", lambda _root: SurrogateReport(responded=True, consumed=False))
    monkeypatch.setattr(
        core,
        "_process_liveness",
        lambda pid: {
            "pid": int(pid),
            "status": "ALIVE" if int(pid) == 5252 else "DEAD",
            "alive": int(pid) == 5252,
            "method": "test",
            "error_code": 0,
        },
    )

    result = core.start_generation_job(
        [sys.executable, "canonical-worker.py", "--resume-run-dir", str(run_dir)],
        cgkn_root=tmp_path,
        artifact_dir=artifact_dir,
        start_timeout=0,
        popen_factory=CapturedResumeProcess,
    )

    assert result["started"] is True
    assert result["deduplicated"] is False
    assert "--resume-run-dir" in CapturedResumeProcess.command
    assert CapturedResumeProcess.command[CapturedResumeProcess.command.index("--resume-run-dir") + 1] == str(run_dir)
    assert result["run_id"] == ""
    assert result["job_id"] != "generation-job-1"


def test_fsv_001_unanswered_replan_remains_deduplicated(tmp_path, monkeypatch):
    artifact_dir, _run_dir = _external_wait_job(tmp_path)
    monkeypatch.setattr(core, "_load_surrogate_adapter", lambda _root: SurrogateReport(responded=False, consumed=False))
    monkeypatch.setattr(
        core,
        "_process_liveness",
        lambda pid: {"pid": int(pid), "status": "DEAD", "alive": False, "method": "test", "error_code": 0},
    )

    result = core.start_generation_job(
        [sys.executable, "canonical-worker.py"],
        cgkn_root=tmp_path,
        artifact_dir=artifact_dir,
        start_timeout=0,
        popen_factory=lambda *_args, **_kwargs: pytest.fail("unanswered external wait must not restart"),
    )

    assert result["deduplicated"] is True
    assert result["state"] == "WAITING_REQUIREMENT_REPLAN"


def test_fsv_001_external_wait_status_is_not_a_dead_worker_failure(tmp_path, monkeypatch):
    artifact_dir, _run_dir = _external_wait_job(tmp_path)
    monkeypatch.setattr(
        core,
        "_process_liveness",
        lambda pid: {"pid": int(pid), "status": "DEAD", "alive": False, "method": "test", "error_code": 0},
    )

    status = core.generation_job_status(artifact_dir)

    assert status["state"] == "WAITING_REQUIREMENT_REPLAN"
    assert status["execution_classification"] == "external_wait"
    assert status["waiting_for"] == "requirement_replan"
    assert "submit" in status["next_action"]
