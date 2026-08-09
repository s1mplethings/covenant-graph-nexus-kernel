from __future__ import annotations

import json

import start_customer_service
from scripts import local_model_router, run_local_pipeline_impl


def test_hybrid_safe_assigns_support_to_local_and_formal_work_to_api(monkeypatch) -> None:
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "hybrid_safe")
    monkeypatch.setenv("CGNK_USE_LOCAL_MODEL", "1")
    monkeypatch.setenv("CGNK_LOCAL_MODEL_TASKS", "all")

    assert local_model_router.task_enabled("customer_classification")
    assert local_model_router.task_enabled("pipeline_planner")
    assert local_model_router.task_enabled("risk_support")
    assert not local_model_router.task_enabled("component_generation")
    assert not local_model_router.task_enabled("component_repair")
    assert not local_model_router.task_enabled("foundation")
    assert not local_model_router.task_enabled("qa")
    assert local_model_router.task_model_owner("component_generation") == "api_provider"


def test_telegram_launcher_defaults_to_hybrid_safe() -> None:
    env = start_customer_service.telegram_model_environment({})
    tasks = set(env["CGNK_LOCAL_MODEL_TASKS"].split(","))

    assert env["CGNK_MODEL_ROUTING_PROFILE"] == "hybrid_safe"
    assert env["CGKN_TELEGRAM_GENERATION_MODE"] == "api"
    assert tasks == local_model_router.HYBRID_SAFE_LOCAL_TASKS
    assert not tasks & local_model_router.HYBRID_SAFE_API_TASKS
    assert env["CGNK_LOCAL_PROVIDER_ATTEMPTS"] == "1"


def test_local_first_requires_explicit_profile() -> None:
    env = start_customer_service.telegram_model_environment({"CGNK_MODEL_ROUTING_PROFILE": "local_first"})
    tasks = set(env["CGNK_LOCAL_MODEL_TASKS"].split(","))

    assert local_model_router.LOCAL_CODE_TASKS <= tasks
    assert "qa" in tasks


def test_component_reasoning_repair_uses_configured_code_model(monkeypatch) -> None:
    monkeypatch.setenv("CGNK_OLLAMA_CODE_MODEL", "unit-code-model")
    monkeypatch.setenv("CGNK_OLLAMA_REASONING_MODEL", "unit-reasoning-model")

    assert local_model_router.choose_ollama_model(
        "http://127.0.0.1:11434",
        "component_reasoning_repair",
    ) == "unit-code-model"


def test_api_only_disables_local_tasks() -> None:
    env = start_customer_service.telegram_model_environment({"CGNK_MODEL_ROUTING_PROFILE": "api_only"})

    assert env["CGNK_USE_LOCAL_MODEL"] == "0"
    assert env["CGNK_LOCAL_MODEL_TASKS"] == ""


def test_hybrid_safe_component_generation_goes_directly_to_api(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "hybrid_safe")
    monkeypatch.setenv("CGNK_USE_LOCAL_MODEL", "1")
    monkeypatch.setattr(
        run_local_pipeline_impl.local_model_router,
        "call_text_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("local code model must not be called")),
    )
    monkeypatch.setattr(
        run_local_pipeline_impl.check_connectivity,
        "_resolve_api_credentials",
        lambda: {"api_key": "test-key", "base_url": "https://api.gptsapi.net/v1"},
    )
    monkeypatch.setattr(
        run_local_pipeline_impl.check_connectivity,
        "_post_json",
        lambda endpoint, payload, token, timeout: (
            {"choices": [{"message": {"content": '{"component_id":"backend","files":[{"path":"main.py","content":"print(1)"}]}'}}]},
            "",
        ),
    )
    phase_log = tmp_path / "provider_phase_log.jsonl"

    raw = run_local_pipeline_impl.provider_text(
        [{"role": "user", "content": "generate"}],
        "gpt-test",
        5,
        stage="component_generation",
        component="backend",
        phase_log_path=phase_log,
    )
    events = [json.loads(line) for line in phase_log.read_text(encoding="utf-8").splitlines()]

    assert '"component_id":"backend"' in raw
    route = next(event for event in events if event.get("event") == "provider_responsibility_route")
    assert route["route"] == "api_direct"
    assert route["owner"] == "api_provider"


def test_explicit_transport_fallback_uses_code_model_without_changing_owner(
    monkeypatch,
) -> None:
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "custom")
    monkeypatch.delenv("CGNK_USE_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("CGNK_LOCAL_MODEL_TASKS", raising=False)
    monkeypatch.setenv("CGNK_OLLAMA_CODE_MODEL", "qwen2.5-coder:7b")
    captured: dict[str, str] = {}

    def fake_ollama(task, system, prompt, timeout):
        captured["task"] = task
        return {
            "ok": True,
            "provider": "ollama",
            "model": "qwen2.5-coder:7b",
            "text": "{}",
        }

    monkeypatch.setattr(local_model_router, "_call_ollama", fake_ollama)

    assert local_model_router.task_model_owner("component_repair") == "api_provider"
    result = local_model_router.call_text_task_fallback(
        "component_repair", "system", "prompt", 30
    )

    assert result["ok"] is True
    assert result["model"] == "qwen2.5-coder:7b"
    assert captured["task"] == "component_repair"
    assert local_model_router.task_model_owner("component_repair") == "api_provider"


def test_provider_transport_failure_records_local_pipeline_fallback(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "custom")
    monkeypatch.delenv("CGNK_USE_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("CGNK_LOCAL_MODEL_TASKS", raising=False)
    monkeypatch.setattr(
        run_local_pipeline_impl.check_connectivity,
        "_resolve_api_credentials",
        lambda: {"api_key": "test-key", "base_url": "https://api.example/v1"},
    )
    monkeypatch.setattr(
        run_local_pipeline_impl.check_connectivity,
        "_post_json",
        lambda *_args, **_kwargs: (None, "HTTP 504 gateway timeout"),
    )
    monkeypatch.setattr(
        run_local_pipeline_impl.check_connectivity,
        "_error_is_retryable",
        lambda _error: True,
    )
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "try_local_provider_text",
        lambda *args, **kwargs: "{\"files\":[]}" if kwargs.get("force_transport_fallback") else None,
    )
    phase_log = tmp_path / "provider_phase_log.jsonl"

    raw = run_local_pipeline_impl.provider_text(
        [{"role": "user", "content": "repair"}],
        "gpt-test",
        5,
        max_attempts=1,
        stage="file_repair",
        component="post_build",
        phase_log_path=phase_log,
    )
    events = [
        json.loads(line)
        for line in phase_log.read_text(encoding="utf-8").splitlines()
    ]

    assert raw == '{"files":[]}'
    fallback = next(event for event in events if event.get("event") == "pipeline_fallback")
    assert fallback["from"] == "api_provider"
    assert fallback["to"] == "local_model"
    assert fallback["task"] == "component_repair"


def test_provider_quota_failure_records_local_pipeline_fallback(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("CGNK_MODEL_ROUTING_PROFILE", "custom")
    monkeypatch.delenv("CGNK_USE_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("CGNK_LOCAL_MODEL_TASKS", raising=False)
    monkeypatch.setattr(
        run_local_pipeline_impl.check_connectivity,
        "_resolve_api_credentials",
        lambda: {"api_key": "test-key", "base_url": "https://api.example/v1"},
    )
    monkeypatch.setattr(
        run_local_pipeline_impl.check_connectivity,
        "_post_json",
        lambda *_args, **_kwargs: (None, 'HTTP 403: {"error":"Key usage limit exceeded"}'),
    )
    monkeypatch.setattr(
        run_local_pipeline_impl,
        "try_local_provider_text",
        lambda *args, **kwargs: "{\"files\":[]}" if kwargs.get("force_transport_fallback") else None,
    )
    phase_log = tmp_path / "provider_phase_log.jsonl"

    raw = run_local_pipeline_impl.provider_text(
        [{"role": "user", "content": "repair"}],
        "gpt-test",
        5,
        max_attempts=1,
        stage="file_repair",
        component="post_build",
        phase_log_path=phase_log,
    )
    events = [json.loads(line) for line in phase_log.read_text(encoding="utf-8").splitlines()]

    assert raw == '{"files":[]}'
    fallback = next(event for event in events if event.get("event") == "pipeline_fallback")
    assert fallback["reason"] == "provider_key_usage_limit"
