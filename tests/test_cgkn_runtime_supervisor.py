from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
from unittest import mock

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for value in (ROOT, SCRIPTS):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

import scripts.cgkn_runtime_supervisor as runtime
import scripts.cgkn_supervision_protocol as protocol
import scripts.codex_conversation as bridge


def _emit(state_dir: pathlib.Path, checkpoint_type: str = "service_startup", action: str = "observe") -> dict:
    return protocol.emit_checkpoint(
        state_dir,
        checkpoint_type,
        repository_root=ROOT,
        reason=f"test {checkpoint_type}",
        requested_action=action,
        conversation_id="chat-1",
        project_id="project-1",
        run_id="run-1",
    )


def _draft(action: str = "resume", repair_targets: list[str] | None = None) -> dict:
    canonical = protocol.canonical_action(action)
    scope = {
        "resume": "none",
        "rework_project": "project",
        "recheck_evidence": "evidence",
        "repair_kernel": "kernel",
        "user_decision": "user",
        "halt": "safety",
    }[canonical]
    return {
        "action": action,
        "scope": scope,
        "summary": "The bounded checkpoint is coherent.",
        "diagnosis": [],
        "evidence_refs": [] if canonical == "resume" else [
            {"role": "test", "ref": "test-evidence.json", "sha256": "a" * 64, "claim": "test contradiction"}
        ],
        "guidance": [],
        "repair_targets": list(repair_targets or []),
        "acceptance_checks": ["Keep the reviewed Provider and delivery route unchanged."],
        "known_limits": ["This is support state, not formal evidence."],
    }


def test_process_liveness_probe_handles_current_process_on_windows() -> None:
    assert runtime.process_is_alive(os.getpid()) is True
    assert runtime.process_is_alive(0) is False
    completed = subprocess.Popen([sys.executable, "-c", "pass"])
    completed.wait(timeout=10)
    assert runtime.process_is_alive(completed.pid) is False


def test_checkpoint_journal_is_hash_linked_and_secret_redacted() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = pathlib.Path(temp_dir)
        first = protocol.emit_checkpoint(
            state_dir,
            "service_startup",
            repository_root=ROOT,
            reason="Bearer abcdefghijklmnopqrstuvwxyz must not persist",
        )
        second = _emit(state_dir, "requirements_frozen")

        assert first["sequence"] == 1
        assert "abcdefghijklmnopqrstuvwxyz" not in first["reason"]
        assert second["sequence"] == 2
        assert second["previous_checkpoint_sha256"] == first["checkpoint_sha256"]
        assert protocol.validate_checkpoint(first) == []
        assert protocol.load_checkpoints(state_dir) == [first, second]

        corrupted = dict(second)
        corrupted["reason"] = "changed"
        assert "checkpoint.checkpoint_sha256" in protocol.validate_checkpoint(corrupted)


def test_result_contract_releases_only_safe_actions_and_rejects_authority_expansion() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = pathlib.Path(temp_dir)
        checkpoint = _emit(state_dir, "pre_public_delivery", "resume")
        result = protocol.build_result(checkpoint, "thread-123", _draft("resume"))
        protocol.append_result(state_dir, result)

        assert protocol.result_for_checkpoint(state_dir, checkpoint["checkpoint_id"]) == result
        assert protocol.await_checkpoint_release(state_dir, checkpoint["checkpoint_id"], 0) == result

        with pytest.raises(ValueError, match="unsafe repair target"):
            protocol.build_result(checkpoint, "thread-123", _draft("repair_kernel", ["generated/app.py"]))
        with pytest.raises(ValueError, match="unsafe repair target"):
            protocol.build_result(checkpoint, "thread-123", _draft("repair_kernel", ["../escape.py"]))

        expanded = dict(result)
        expanded["delivery_allowed"] = True
        expanded["result_sha256"] = protocol.canonical_hash(
            protocol._without_hash(expanded, "result_sha256")
        )
        assert "result.forbidden_authority_field" in protocol.validate_result(expanded, checkpoint)


def test_codex_cli_adapter_starts_then_resumes_the_same_thread() -> None:
    calls: list[list[str]] = []
    run_options: list[dict] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        run_options.append(dict(kwargs))
        output_path = pathlib.Path(argv[argv.index("--output-last-message") + 1])
        output_path.write_text(json.dumps(_draft("resume")), encoding="utf-8")
        stdout = json.dumps({"type": "thread.started", "thread_id": "thread-persistent"}) if "resume" not in argv else ""
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = pathlib.Path(temp_dir)
        adapter = runtime.CodexCliThreadAdapter(
            ROOT,
            state_dir,
            codex_command=sys.executable,
            runner=fake_run,
        )
        host = runtime.SupervisorHost(ROOT, state_dir, adapter)
        _emit(state_dir, "requirements_frozen")
        _emit(state_dir, "integration_complete")

        first = host.process_next()
        second = host.process_next()
        state = host.load_state()

        assert first["thread_id"] == "thread-persistent"
        assert second["thread_id"] == "thread-persistent"
        assert "resume" not in calls[0]
        assert "resume" in calls[1]
        assert "thread-persistent" in calls[1]
        assert all(options["encoding"] == "utf-8" for options in run_options)
        assert all(options["errors"] == "replace" for options in run_options)
        assert state["thread_id"] == "thread-persistent"
        assert state["last_checkpoint_sequence"] == 2
        assert state["workflow_state"] == "ready"


def test_supervisor_detects_cursor_discontinuity_before_invoking_codex() -> None:
    adapter = mock.Mock()
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = pathlib.Path(temp_dir)
        host = runtime.SupervisorHost(ROOT, state_dir, adapter)
        first = _emit(state_dir, "service_startup")
        state = host.load_state()
        state["last_checkpoint_sequence"] = 1
        state["last_checkpoint_sha256"] = "wrong"
        host.save_state(state)
        _emit(state_dir, "requirements_frozen")

        with pytest.raises(RuntimeError, match="continuity"):
            host.process_next()
        adapter.run.assert_not_called()
        assert host.load_state()["workflow_state"] == "checkpoint_discontinuity"
        assert first["checkpoint_sha256"] != "wrong"


def test_positive_transition_gate_waits_then_accepts_matching_supervisor_release() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        state_dir = root / "supervisor"
        session_dir = root / "sessions"
        session_dir.mkdir(parents=True)
        session = bridge.default_session("chat-gate")
        session["whiteboard"]["project_summary"] = "做一个单功能学习计划工具"

        previous_dir = bridge.RUNTIME_SUPERVISOR_DIR
        previous_policy = bridge.SUPERVISION_POLICY
        previous_timeout = bridge.SUPERVISION_GATE_TIMEOUT
        bridge.RUNTIME_SUPERVISOR_DIR = str(state_dir)
        bridge.SUPERVISION_POLICY = "gate"
        bridge.SUPERVISION_GATE_TIMEOUT = 0
        try:
            first = bridge.run_positive_transition_audit(
                session_dir,
                "chat-gate",
                session,
                "pre_public_delivery",
                reason="test positive claim",
                context_refs=[{"role": "test", "ref": "evidence.json", "sha256": "a" * 64}],
            )
            assert first["action"] == "halt"
            assert first["audit_status"] == "timeout"
            checkpoint = protocol.load_checkpoints(state_dir)[0]
            result = protocol.build_result(checkpoint, "thread-gate", _draft("resume"))
            protocol.append_result(state_dir, result)
            assert protocol.await_checkpoint_release(state_dir, checkpoint["checkpoint_id"], 0)["action"] == "resume"
        finally:
            bridge.RUNTIME_SUPERVISOR_DIR = previous_dir
            bridge.SUPERVISION_POLICY = previous_policy
            bridge.SUPERVISION_GATE_TIMEOUT = previous_timeout


def test_bridge_and_supervisor_keep_formal_authorities_outside_runtime_protocol() -> None:
    bridge_source = (SCRIPTS / "codex_conversation.py").read_text(encoding="utf-8")
    host_source = (SCRIPTS / "cgkn_runtime_supervisor.py").read_text(encoding="utf-8")
    protocol_source = (SCRIPTS / "cgkn_supervision_protocol.py").read_text(encoding="utf-8")

    assert "validate_provider_generation_output" in bridge_source
    assert "local_packager" in bridge_source
    assert "public_delivery_gate" in bridge_source
    assert "run_provider_execute_with_retries" not in host_source
    assert "local_packager" not in host_source
    assert '"candidate_write_authorized": False' in protocol_source
    assert '"delivery_authorized": False' in protocol_source
