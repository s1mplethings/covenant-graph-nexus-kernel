from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import threading
import time

import pytest

from cgkn_agent_kit import core
from cgkn_agent_kit.cli import _emit, main


CGKN_ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.mark.skipif(os.name != "nt", reason="Windows process-query acceptance")
def test_windows_liveness_probe_is_non_destructive() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        observations = [core._process_liveness(child.pid) for _ in range(3)]
        assert [item["status"] for item in observations] == ["ALIVE"] * 3
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=10)
    assert core._process_liveness(child.pid)["status"] == "DEAD"


def test_real_worker_exit_is_reconciled_without_synthetic_state_mutation(tmp_path: pathlib.Path) -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    core.write_json(
        core.generation_job_path(tmp_path),
        {"job_id": "real-exit", "state": "RUNNING", "process_id": child.pid},
    )
    try:
        assert core.generation_job_status(tmp_path)["state"] == "RUNNING"
        child.terminate()
        child.wait(timeout=10)
        observed = core.generation_job_status(tmp_path)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
    assert observed["state"] == "FAILED"
    assert observed["terminal_reason"] == "WORKER_PROCESS_NOT_ALIVE"
    assert observed["execution_classification"] == "worker_exit"


@pytest.mark.parametrize("state", ["STARTING", "RUNNING", "WAITING"])
def test_dead_active_generation_job_is_durably_reconciled(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    core.write_json(core.generation_job_path(tmp_path), {"job_id": "old", "state": state, "process_id": 99})
    monkeypatch.setattr(core, "_process_liveness", lambda pid: {"pid": pid, "status": "DEAD", "alive": False, "method": "test", "error_code": 0})
    observed = core.generation_job_status(tmp_path)
    durable = core.read_json(core.generation_job_path(tmp_path))
    assert observed["state"] == durable["state"] == "FAILED"
    assert durable["terminal_reason"] == "WORKER_PROCESS_NOT_ALIVE"


def test_live_external_wait_is_not_misclassified_as_worker_failure(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    core.write_json(core.generation_job_path(tmp_path), {"job_id": "wait-1", "state": "WAITING_SURROGATE_RESPONSE", "process_id": 99})
    monkeypatch.setattr(core, "_process_liveness", lambda pid: {"pid": pid, "status": "ALIVE", "alive": True, "method": "test", "error_code": 0})
    observed = core.generation_job_status(tmp_path)
    assert observed["state"] == "WAITING_SURROGATE_RESPONSE"
    assert observed["job_alive"] is True


@pytest.mark.parametrize(("state", "waiting_for"), [("WAITING_SURROGATE_RESPONSE", "surrogate_response"), ("WAITING_REQUIREMENT_REPLAN", "requirement_replan")])
def test_external_wait_survives_expected_worker_exit(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, state: str, waiting_for: str) -> None:
    core.write_json(core.generation_job_path(tmp_path), {"job_id": "wait-2", "state": state, "process_id": 99})
    monkeypatch.setattr(core, "_process_liveness", lambda pid: {"pid": pid, "status": "DEAD", "alive": False, "method": "test", "error_code": 0})
    observed = core.generation_job_status(tmp_path)
    assert observed["state"] == state
    assert observed["execution_classification"] == "external_wait"
    assert observed["waiting_for"] == waiting_for


def test_cancel_is_identity_bound_idempotent_and_rejects_late_result(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = core.generation_job_path(tmp_path)
    result_path = tmp_path / "generation_result.json"
    core.write_json(path, {"job_id": "job-current", "attempt_id": "attempt-current", "run_id": "run-current", "state": "WAITING_SURROGATE_RESPONSE", "process_id": 99, "process_identity": "test-process-99", "result_path": str(result_path)})
    alive = {99: True}
    monkeypatch.setattr(core, "_process_liveness", lambda pid: {"pid": pid, "status": "ALIVE" if alive.get(pid) else "DEAD", "alive": bool(alive.get(pid)), "method": "test", "error_code": 0})
    monkeypatch.setattr(core, "_process_identity_token", lambda pid: f"test-process-{pid}")

    def terminate(pid: int) -> None:
        alive[pid] = False

    with pytest.raises(core.AgentKitError, match="identity mismatch"):
        core.cancel_generation_job(tmp_path, expected_job_id="wrong", terminate=terminate)
    cancelled = core.cancel_generation_job(tmp_path, expected_job_id="job-current", terminate=terminate)
    assert cancelled["state"] == "CANCELLED" and cancelled["cancelled"] is True
    assert core.cancel_generation_job(tmp_path, expected_job_id="job-current", terminate=terminate)["deduplicated"] is True
    core.write_json(result_path, {"generation_job_id": "job-current", "generation_attempt_id": "attempt-current", "run_id": "run-current", "candidate_hash": "late"})
    observed = core.generation_job_status(tmp_path)
    assert observed["candidate_present"] is False


def test_result_from_replaced_job_identity_is_not_admitted(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result_path = tmp_path / "generation_result.json"
    core.write_json(core.generation_job_path(tmp_path), {"job_id": "new-job", "run_id": "new-run", "state": "COMPLETE", "process_id": 0, "result_path": str(result_path)})
    core.write_json(result_path, {"generation_job_id": "old-job", "run_id": "new-run", "candidate_hash": "stale"})
    monkeypatch.setattr(core, "_process_liveness", lambda pid: {"pid": pid, "status": "DEAD", "alive": False, "method": "test", "error_code": 0})
    assert core.generation_job_status(tmp_path)["candidate_present"] is False


def test_result_without_complete_job_and_attempt_identity_is_quarantined(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result_path = tmp_path / "generation_result.json"
    core.write_json(core.generation_job_path(tmp_path), {"job_id": "job", "attempt_id": "attempt", "run_id": "run", "state": "COMPLETE", "process_id": 0, "result_path": str(result_path)})
    monkeypatch.setattr(core, "_process_liveness", lambda pid: {"pid": pid, "status": "DEAD", "alive": False, "method": "test", "error_code": 0})
    for incomplete in (
        {"run_id": "run", "candidate_hash": "missing-job"},
        {"generation_job_id": "job", "run_id": "run", "candidate_hash": "missing-attempt"},
    ):
        core.write_json(result_path, incomplete)
        observed = core.generation_job_status(tmp_path)
        assert observed["candidate_present"] is False
        assert observed["result_identity_valid"] is False


def test_matching_result_identity_is_admitted(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result_path = tmp_path / "generation_result.json"
    core.write_json(core.generation_job_path(tmp_path), {"job_id": "job", "attempt_id": "attempt", "run_id": "run", "state": "COMPLETE", "process_id": 0, "result_path": str(result_path)})
    core.write_json(result_path, {"generation_job_id": "job", "generation_attempt_id": "attempt", "run_id": "run", "candidate_hash": "current"})
    monkeypatch.setattr(core, "_process_liveness", lambda pid: {"pid": pid, "status": "DEAD", "alive": False, "method": "test", "error_code": 0})
    observed = core.generation_job_status(tmp_path)
    assert observed["candidate_present"] is True
    assert observed["result_identity_valid"] is True


def test_cancel_requires_identity_and_cannot_overwrite_replacement(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = core.generation_job_path(tmp_path)
    core.write_json(path, {"job_id": "old-job", "attempt_id": "old-attempt", "state": "RUNNING", "process_id": 0})
    monkeypatch.setattr(core, "_process_liveness", lambda pid: {"pid": pid, "status": "DEAD", "alive": False, "method": "test", "error_code": 0})
    with pytest.raises(TypeError):
        core.cancel_generation_job(tmp_path)

    errors: list[BaseException] = []
    with core.generation_job_lock(tmp_path):
        thread = threading.Thread(
            target=lambda: _capture_cancel_error(core, tmp_path, errors),
            daemon=True,
        )
        thread.start()
        time.sleep(0.05)
        core.write_json(path, {"job_id": "new-job", "attempt_id": "new-attempt", "state": "WAITING_SURROGATE_RESPONSE", "process_id": 0})
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], core.AgentKitError)
    assert core.read_json(path)["job_id"] == "new-job"
    assert core.read_json(path)["state"] == "WAITING_SURROGATE_RESPONSE"


def test_cancel_does_not_signal_reused_pid(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = core.generation_job_path(tmp_path)
    core.write_json(path, {
        "job_id": "job",
        "attempt_id": "attempt",
        "state": "RUNNING",
        "process_id": 4321,
        "process_identity": "original-process",
    })
    monkeypatch.setattr(core, "_process_identity_token", lambda pid: "replacement-process")
    monkeypatch.setattr(core, "_process_liveness", lambda pid: {"pid": pid, "status": "ALIVE", "alive": True, "method": "test", "error_code": 0})
    signalled: list[int] = []

    observed = core.cancel_generation_job(
        tmp_path,
        expected_job_id="job",
        terminate=signalled.append,
    )

    assert observed["state"] == "CANCELLED"
    assert signalled == []


def _capture_cancel_error(core_module, artifact_dir: pathlib.Path, errors: list[BaseException]) -> None:
    try:
        core_module.cancel_generation_job(artifact_dir, expected_job_id="old-job")
    except BaseException as exc:
        errors.append(exc)


def test_unknown_active_generation_job_deduplicates(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    core.write_json(core.generation_job_path(tmp_path), {"job_id": "old", "state": "RUNNING", "process_id": 99})
    monkeypatch.setattr(core, "_process_liveness", lambda pid: {"pid": pid, "status": "UNKNOWN", "alive": True, "method": "test", "error_code": 5})
    result = core.start_generation_job(["python", "worker.py"], cgkn_root=tmp_path, artifact_dir=tmp_path, popen_factory=lambda *a, **k: pytest.fail("must not spawn"))
    assert result["deduplicated"] is True


def test_answered_surrogate_wait_starts_new_attempt(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = core.generation_job_path(tmp_path)
    core.write_json(path, {"job_id": "waiting", "attempt_id": "old-attempt", "state": "WAITING_SURROGATE_RESPONSE", "process_id": 99, "run_dir": str(tmp_path / "run")})
    monkeypatch.setattr(core, "_surrogate_response_ready", lambda cgkn_root, job: True)

    class Process:
        pid = 1234

    monkeypatch.setattr(core, "_process_identity_token", lambda pid: "test-process-1234")
    monkeypatch.setattr(core, "generation_job_status", lambda artifact_dir: {**core.read_json(path), "state": "RUNNING", "run_id": "resumed-run"})
    result = core.start_generation_job(
        ["python", "worker.py"], cgkn_root=tmp_path, artifact_dir=tmp_path,
        start_timeout=0, popen_factory=lambda *args, **kwargs: Process(),
    )
    saved = core.read_json(path)
    assert result["started"] is True and result["deduplicated"] is False
    assert saved["job_id"] != "waiting"
    assert saved["attempt_id"] != "old-attempt"


def test_unanswered_surrogate_wait_still_deduplicates(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    core.write_json(core.generation_job_path(tmp_path), {"job_id": "waiting", "attempt_id": "old-attempt", "state": "WAITING_SURROGATE_RESPONSE", "process_id": 99, "run_dir": str(tmp_path / "run")})
    monkeypatch.setattr(core, "_surrogate_response_ready", lambda cgkn_root, job: False)
    result = core.start_generation_job(
        ["python", "worker.py"], cgkn_root=tmp_path, artifact_dir=tmp_path,
        popen_factory=lambda *args, **kwargs: pytest.fail("must not spawn"),
    )
    assert result["started"] is False and result["deduplicated"] is True


def test_dead_generation_job_starts_new_identity_and_preserves_spawn_race(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = core.generation_job_path(tmp_path)
    core.write_json(path, {"job_id": "old", "state": "WAITING", "process_id": 99})
    monkeypatch.setattr(core, "_process_liveness", lambda pid: {"pid": pid, "status": "DEAD" if pid == 99 else "ALIVE", "alive": pid != 99, "method": "test", "error_code": 0})
    class Process:
        pid = 100
    def spawn(command, **kwargs):
        job_id = command[command.index("--generation-job-id") + 1]
        attempt_id = command[command.index("--generation-attempt-id") + 1]
        core.write_json(path, {"job_id": job_id, "attempt_id": attempt_id, "state": "RUNNING", "run_id": "abc", "process_id": 0, "revision": 2})
        return Process()
    result = core.start_generation_job(["python", "worker.py"], cgkn_root=tmp_path, artifact_dir=tmp_path, start_timeout=0, popen_factory=spawn)
    assert result["started"] is True and result["deduplicated"] is False
    assert result["job_id"] != "old" and result["state"] == "RUNNING" and result["run_id"] == "abc"


def test_cli_json_output_reconfigures_legacy_windows_stream_to_utf8() -> None:
    class LegacyStream:
        def __init__(self) -> None:
            self.encoding = "cp1252"
            self.errors = "strict"
            self.value = ""

        def reconfigure(self, *, encoding: str, errors: str) -> None:
            self.encoding = encoding
            self.errors = errors

        def write(self, value: str) -> int:
            value.encode(self.encoding, errors=self.errors)
            self.value += value
            return len(value)

        def flush(self) -> None:
            return None

    stream = LegacyStream()
    _emit({"message": "中文路径"}, stream=stream)
    assert stream.encoding == "utf-8"
    assert "中文路径" in stream.value


def initialized(tmp_path: pathlib.Path) -> pathlib.Path:
    project = tmp_path / "sample project"
    project.mkdir()
    core.initialize_project(project, CGKN_ROOT)
    return project


def test_init_is_project_local_and_does_not_store_secrets(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    config = json.loads((project / ".cgkn" / "agent-kit.json").read_text(encoding="utf-8"))

    assert config["stores_secrets"] is False
    assert config["provider_entrypoint"] == "scripts/run_codex_conversation_generation.py"
    assert (project / ".cgkn" / "agent-kit" / ".gitignore").read_text(encoding="utf-8") == "*\n!.gitignore\n"
    assert list(project.iterdir()) == [project / ".cgkn"]


def test_scan_is_bounded_and_excludes_secret_and_build_paths(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    (project / "README.md").write_text("Project overview", encoding="utf-8")
    fake_secret = "sk-" + ("a" * 20)
    (project / "main.py").write_text(f'API_TOKEN="{fake_secret}"\nprint("ok")', encoding="utf-8")
    (project / ".env").write_text("OPENAI_API_KEY=not-readable", encoding="utf-8")
    (project / "credentials.json").write_text('{"password":"never-read"}', encoding="utf-8")
    (project / "node_modules").mkdir()
    (project / "node_modules" / "library.js").write_text("ignored", encoding="utf-8")

    context = core.scan_project(project, max_items=2)
    serialized = json.dumps(context)

    assert len(context["selected_items"]) == 2
    assert context["selected_items"][0]["path"] == "README.md"
    assert fake_secret not in serialized
    assert "never-read" not in serialized
    assert "[REDACTED]" in serialized
    assert all("node_modules" not in item["path"] for item in context["selected_items"])


def test_prepare_and_manual_seal_use_real_supervisor_contract(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    (project / "README.md").write_text("A small inventory CLI", encoding="utf-8")
    request = core.prepare_request(
        project, goal="Build the inventory CLI", gap="Need bounded architecture guidance",
        category="planning_gap",
    )
    draft = project / "draft.json"
    core.write_json(draft, {
        "workflow_state": "ready",
        "summary": "Use a compact domain, repository, service, and CLI design.",
        "diagnosis": ["The interface boundary is not yet explicit."],
        "provider_guidance": ["Give persistence and CLI parsing separate owners."],
        "repair_targets": ["src/main.py"],
        "acceptance_checks": ["Run add, list, update, and delete through the real CLI."],
        "context_requests": [],
        "tool_evidence_requests": ["Run the generated test suite."],
        "known_limits": ["Advisory guidance is not delivery evidence."],
    })

    brief = core.seal_draft(project, request, draft)
    value = core.read_json(brief)

    assert value["kind"] == "CGKNCodexCapabilityBrief"
    assert value["authority"]["candidate_write_authorized"] is False
    assert value["authority"]["formal_evidence_status"] == "NOT_EVALUATED"
    assert (project / ".cgkn" / "agent-kit" / "whiteboard_patch.json").is_file()
    assert len((project / ".cgkn" / "agent-kit" / "agent_session.jsonl").read_text(encoding="utf-8").splitlines()) == 3


def test_codex_invocation_is_ephemeral_read_only_and_schema_constrained(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = initialized(tmp_path)
    request = project / ".cgkn" / "agent-kit" / "request.json"
    core.write_json(request, {"kind": "test-request"})
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], *, cwd: pathlib.Path, input_text: str | None = None, timeout: int = 600):
        captured.update(argv=argv, cwd=cwd, input_text=input_text, timeout=timeout)
        output = pathlib.Path(argv[argv.index("--output-last-message") + 1])
        core.write_json(output, {"workflow_state": "needs_context"})
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(core, "_run", fake_run)
    draft = core.codex_draft(project, request, codex_command="codex-test", timeout=77)
    argv = captured["argv"]

    assert draft.is_file()
    assert argv[:2] == ["codex-test", "exec"]
    assert "--ephemeral" in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--output-schema" in argv
    assert "danger-full-access" not in argv
    assert captured["cwd"] == project.resolve()


def test_doctor_reports_unusable_codex_without_faking_readiness(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    report = core.doctor(project, codex_command=str(tmp_path / "missing-codex.exe"))

    assert report["provider_mainline_available"] is True
    assert report["ready_for_manual_agent"] is True
    assert report["ready_for_codex_automation"] is False
    assert report["codex"]["usable"] is False


def test_project_config_cannot_redirect_support_artifacts_outside_dot_cgkn(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    config_path = project / ".cgkn" / "agent-kit.json"
    config = core.read_json(config_path)
    config["artifact_dir"] = "../outside"
    core.write_json(config_path, config)

    with pytest.raises(core.AgentKitError, match="relative path under .cgkn"):
        core.load_project(project)


def test_explicit_wrong_cgkn_root_is_not_silently_replaced(tmp_path: pathlib.Path) -> None:
    with pytest.raises(core.AgentKitError, match="Not a compatible CGKN checkout"):
        core.resolve_cgkn_root(str(tmp_path / "wrong"))


def test_generation_command_has_one_formal_entry_and_no_secret_argument(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    brief = project / "brief.json"
    argv = core.generation_command(
        project, goal="Build a useful CLI", brief_path=brief,
        out_dir=project / "generated output", allow_network=True,
    )
    joined = " ".join(argv)

    assert argv[1] == str(CGKN_ROOT / "scripts" / "run_codex_conversation_generation.py")
    assert "--codex-capability-brief" in argv
    assert "--use-api" in argv and "--allow-provider" in argv
    assert "--allow-network" in argv
    assert "--api-key" not in argv
    assert "local_packager.py" not in joined
    assert "run_local_pipeline.py" not in joined


def test_generation_command_routes_every_provider_stage_to_selected_model(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    selected_model = "qwen3.8-max"

    argv = core.generation_command(
        project,
        goal="Build a useful CLI",
        brief_path=project / "brief.json",
        model=selected_model,
    )

    assert argv[argv.index("--model") + 1] == selected_model
    assert argv[argv.index("--small-model") + 1] == selected_model
    assert argv[argv.index("--large-model") + 1] == selected_model


def test_generation_command_can_select_the_existing_formal_resume_route(tmp_path: pathlib.Path) -> None:
    project = initialized(tmp_path)
    run_dir = project / ".cgkn" / "agent-kit" / "runs"
    argv = core.generation_command(
        project,
        goal="Resume a useful CLI",
        brief_path=project / "brief.json",
        resume_run_dir=run_dir,
    )

    assert argv[-2:] == ["--resume-run-dir", str(run_dir.resolve())]


def test_cli_dry_run_works_from_path_with_spaces(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = initialized(tmp_path)
    exit_code = main(["generate", "--project", str(project), "--goal", "Build a CLI", "--dry-run"])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["executed"] is False
    assert output["secrets_in_argv"] is False
    assert str(project.resolve()) in " ".join(output["argv"])


def test_usage_beta_build_defaults_to_canonical_surrogate(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = initialized(tmp_path)
    exit_code = main(["build", "Build a useful local tool", "--project", str(project), "--usage-beta", "--dry-run"])
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["profile"] == "usage_beta"
    assert output["execution_mode"] == "codex_surrogate"
    assert "--use-api" not in output["argv"]
    assert "--allow-provider" not in output["argv"]


def test_usage_beta_explicit_live_never_falls_back(tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = initialized(tmp_path)
    exit_code = main(["build", "Build a useful local tool", "--project", str(project), "--usage-beta", "--provider-mode", "live", "--dry-run"])
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["execution_mode"] == "live"
    assert "--use-api" in output["argv"]
    assert "--allow-provider" in output["argv"]
