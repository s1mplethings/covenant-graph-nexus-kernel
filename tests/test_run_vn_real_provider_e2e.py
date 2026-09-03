from __future__ import annotations

import pathlib
import threading

import pytest

pytestmark = pytest.mark.e2e

from scripts import run_vn_real_provider_e2e as runner
from scripts import run_local_pipeline_impl


def test_capture_codex_conversation_returns_bound_artifact_identity(tmp_path: pathlib.Path) -> None:
    artifact = tmp_path / "project.zip"
    artifact.write_bytes(b"project")
    client = runner.CaptureCodexConversation()

    result = client.send_document("conversation-1", artifact, "项目包")

    assert result["ok"] is True
    assert result["result"]["conversation_id"] == "conversation-1"
    assert result["result"]["turn_id"]
    assert result["result"]["artifact_id"]
    assert result["result"]["artifact_unique_id"] == result["result"]["artifact_id"]
    assert client.documents == [result["result"]]


def test_real_provider_parser_uses_codex_conversation_identity() -> None:
    args = runner.build_parser().parse_args(["--conversation-id", "conversation-2"])
    assert args.conversation_id == "conversation-2"


def test_real_provider_flow_confirms_design_before_generation() -> None:
    assert "确认设计" in runner.START_TEXT


def test_inline_conversation_threading_does_not_replace_python_thread_class() -> None:
    system_thread = threading.Thread
    original_bridge_threading = runner.bridge.threading
    try:
        runner.bridge.threading = runner.InlineThreadingNamespace(original_bridge_threading)
        assert runner.bridge.threading.Thread is runner.InlineThread
        assert runner.bridge.threading.get_ident is threading.get_ident
        assert threading.Thread is system_thread
    finally:
        runner.bridge.threading = original_bridge_threading


def test_run_model_override_applies_to_every_task_and_restores(monkeypatch) -> None:
    env_names = {
        *runner.bridge.model_policy.TASK_ENV_VARS.values(),
        "CGNK_PROVIDER_SMALL_MODEL",
        "CGNK_PROVIDER_LARGE_MODEL",
    }
    for env_name in env_names:
        monkeypatch.delenv(env_name, raising=False)

    previous = runner.apply_task_model_override("qwen3-coder-plus")
    try:
        assert all(
            runner.bridge.model_policy.select_model(task) == "qwen3-coder-plus"
            for task in runner.bridge.model_policy.TASK_ENV_VARS
        )
        routing = run_local_pipeline_impl.provider_model_routing_policy_from_args()
        route = run_local_pipeline_impl.choose_provider_model(
            "component_file_generation",
            4000,
            "qwen3-coder-plus",
            routing,
        )
        assert routing.small_model == "qwen3-coder-plus"
        assert routing.large_model == "qwen3-coder-plus"
        assert route["selected_model"] == "qwen3-coder-plus"
    finally:
        runner.restore_task_model_override(previous)

    assert all(env_name not in runner.os.environ for env_name in env_names)


def test_provider_quota_failure_is_classified_as_blocked_provider() -> None:
    status, blocked = runner.classify_e2e_status(
        success_ready=False,
        retryable_rework_verified=False,
        smoke={"provider_error_type": "PROVIDER_FORBIDDEN"},
    )
    assert status == "BLOCKED_PROVIDER"
    assert blocked is True


def test_internal_real_project_failure_remains_fail() -> None:
    status, blocked = runner.classify_e2e_status(
        success_ready=False,
        retryable_rework_verified=False,
        smoke={},
    )
    assert status == "FAIL"
    assert blocked is False


def test_quality_gate_rework_is_formal_needs_rework() -> None:
    status, blocked = runner.classify_e2e_status(
        success_ready=False,
        retryable_rework_verified=False,
        smoke={"ok": True},
        generation={"status": "rework_blocked"},
        public_delivery_gate={"status": "NEEDS_REWORK"},
    )

    assert status == "NEEDS_REWORK"
    assert blocked is False
