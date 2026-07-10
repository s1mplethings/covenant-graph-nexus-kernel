from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_leaf_provider_guard import build_leaf_provider_prompt, build_provider_request, call_responses_provider, classify_provider_error, redact_secret, save_redacted_provider_request
from scripts.agent_real_provider_leaf_builder import _test_leaf_read_context


def test_provider_guard_prompt_limits_leaf_scope_and_redacts_request(tmp_path: pathlib.Path) -> None:
    prompt = build_leaf_provider_prompt(
        agent_id="search_service_leaf",
        allowed_files=["app/services/search_service.py", "tests/test_search_service.py"],
        forbidden_files=["README.md", "app/main.py"],
        user_goal="Local AI Knowledge Studio",
    )
    request = build_provider_request(model="gpt-5.4-nano", prompt=prompt)
    assert request["max_tokens"] == 9000
    fake_secret = "sk-" + "s" * 16
    request["api_key"] = fake_secret
    save_redacted_provider_request(out_dir=tmp_path, request_doc=request, prompt=prompt)

    assert "You cannot generate the whole project" in prompt
    assert "allowed_files" in prompt
    saved = json.loads((tmp_path / "provider_request_redacted.json").read_text(encoding="utf-8"))
    assert fake_secret not in json.dumps(saved)
    assert "<redacted>" in redact_secret("Bearer " + fake_secret)


def test_provider_guard_prompt_defines_backend_leaf_interfaces() -> None:
    expected = {
        "document_import_leaf": "import_document(title, content)",
        "search_service_leaf": "search_documents(documents, query)",
        "model_adapter_leaf": "adapter_status(config=None)",
        "task_service_leaf": "create_task(title)",
        "report_service_leaf": "build_report(documents, tasks)",
    }
    for leaf, signature in expected.items():
        prompt = build_leaf_provider_prompt(
            agent_id=leaf,
            allowed_files=["app/services/example.py", "tests/test_example.py"],
            forbidden_files=["README.md"],
            user_goal="Local AI Knowledge Studio",
        )
        assert signature in prompt
        assert "You cannot generate the whole project" in prompt


def test_search_leaf_prompt_requires_field_names_and_values() -> None:
    prompt = build_leaf_provider_prompt(
        agent_id="search_service_leaf",
        allowed_files=["app/services/search_service.py", "tests/test_search_service.py"],
        forbidden_files=["README.md"],
        user_goal="Local Studio Operations Hub",
    )

    assert "field names and field values" in prompt
    assert "version 13" in prompt


def test_provider_guard_prompt_defines_frontend_leaf_interfaces() -> None:
    expected = {
        "dashboard_page_leaf": "complete HTML dashboard template",
        "documents_page_leaf": "complete HTML documents template",
        "search_page_leaf": "complete HTML search template",
        "tasks_page_leaf": "complete HTML tasks template",
        "reports_page_leaf": "complete HTML reports template",
        "settings_page_leaf": "complete HTML settings template",
        "smoke_test_leaf": "pytest smoke test file only",
        "backend_tests_leaf": "pytest integration test file only",
        "ui_route_tests_leaf": "pytest route test file only",
    }
    for leaf, phrase in expected.items():
        prompt = build_leaf_provider_prompt(
            agent_id=leaf,
            allowed_files=["app/templates/example.html"],
            forbidden_files=["README.md"],
            user_goal="Local AI Knowledge Studio",
        )
        assert phrase in prompt
        assert "You can generate only the files listed in allowed_files" in prompt


def test_provider_guard_classifies_codex_lite_model_unsupported_as_provider_block() -> None:
    result = classify_provider_error("This model is not supported when using X-OpenAI-Internal-Codex-Responses-Lite.")

    assert result["classification"] == "provider_unavailable"
    assert result["failure_type"] == "provider_model_unsupported"
    assert result["verdict"] == "BLOCKED"
    assert result["not_proven"] is True
    assert result["fake_success"] is False


def test_responses_provider_retries_transient_disconnect(monkeypatch) -> None:
    calls = []

    def fake_post(endpoint, payload, token, timeout):
        calls.append(endpoint)
        if len(calls) == 1:
            return None, "request failed: RemoteDisconnected [retryable=true]"
        return {"status": "completed"}, ""

    monkeypatch.setattr("scripts.agent_leaf_provider_guard.check_connectivity._post_json", fake_post)
    doc, error, attempts = call_responses_provider(
        base_url="https://api.gptsapi.net/v1",
        token="secret",
        payload={"model": "gpt-5.4-nano", "input": "ping"},
        timeout=10,
    )

    assert doc == {"status": "completed"}
    assert error == ""
    assert attempts == 2
    assert calls == [
        "https://api.gptsapi.net/v1/responses",
        "https://api.gptsapi.net/v1/responses",
    ]


def test_responses_provider_does_not_retry_non_retryable_error(monkeypatch) -> None:
    calls = []

    def fake_post(endpoint, payload, token, timeout):
        calls.append(endpoint)
        return None, "HTTP 403: Key usage limit exceeded [retryable=false]"

    monkeypatch.setattr("scripts.agent_leaf_provider_guard.check_connectivity._post_json", fake_post)

    doc, error, attempts = call_responses_provider(
        base_url="https://api.gptsapi.net/v1",
        token="secret",
        payload={"model": "gpt-5.4-nano", "input": "ping"},
        timeout=10,
    )

    assert doc is None
    assert "HTTP 403" in error
    assert attempts == 1
    assert calls == ["https://api.gptsapi.net/v1/responses"]


def test_provider_guard_classifies_method_unsupported_as_blocked_not_proven() -> None:
    result = classify_provider_error('HTTP 400: {"error":"model does not support this API"} [retryable=false]')

    assert result["classification"] == "provider_unavailable"
    assert result["failure_type"] == "provider_method_unsupported"
    assert result["provider_error_type"] == "PROVIDER_METHOD_UNSUPPORTED"
    assert result["verdict"] == "BLOCKED"
    assert result["not_proven"] is True
    assert result["fake_success"] is False


def test_ui_test_leaf_receives_read_only_integration_context(tmp_path: pathlib.Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "main.py").write_text("def create_app():\\n    return Handler\\n", encoding="utf-8")
    (app / "routes.py").write_text("def render_page(page):\\n    return page\\n", encoding="utf-8")

    context = _test_leaf_read_context(tmp_path, "ui_route_tests_leaf_v2")

    assert "read-only" in context
    assert "def create_app()" in context
    assert "def render_page(page)" in context
    assert _test_leaf_read_context(tmp_path, "search_service_leaf") == ""
