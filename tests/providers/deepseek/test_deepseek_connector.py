from __future__ import annotations

import json

import pytest

from cgkn.providers import DeepSeekConnector, ModelRoleConfig, ProviderConnectionError, StructuredOutputMode
from cgkn.providers.structured_output import parse_and_validate, resolve_credential, sanitize_vendor_text

pytestmark = [pytest.mark.happy_path, pytest.mark.negative, pytest.mark.boundary, pytest.mark.fault_injection, pytest.mark.security]


PROFILE = {"provider_id": "deepseek", "base_url": "https://api.deepseek.com/v1", "preferred_models": ["deepseek-flash"], "timeout": 10, "max_output_tokens": 100}


class Response:
    def __init__(self, value): self.value = value; self.status = 200
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self, _limit): return json.dumps(self.value).encode()


def test_deepseek_json_object_then_local_schema_validation(monkeypatch) -> None:
    calls = []
    replies = iter([{"data": [{"id": "deepseek-flash"}]}, {"id": "d1", "model": "deepseek-flash", "choices": [{"message": {"content": "{\"ok\":true}"}}]}])
    def fake(req, timeout): calls.append(json.loads(req.data) if req.data else None); return Response(next(replies))
    monkeypatch.setattr("cgkn.providers.connectors.deepseek.request.urlopen", fake)
    connector = DeepSeekConnector(PROFILE, environment={"DEEPSEEK_API_KEY": "secret"})
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
    result = connector.complete_structured(system="s", user="u", schema_name="probe", schema=schema, config=ModelRoleConfig("worker", "deepseek", 10, 10))
    assert result.attempts == 1
    assert calls[-1]["response_format"] == {"type": "json_object"}
    assert connector.supports_structured_output() is StructuredOutputMode.PROMPT_JSON_LOCAL_VALIDATE


def test_deepseek_format_repair_cannot_change_existing_semantics(monkeypatch) -> None:
    replies = iter([{"data": [{"id": "deepseek-flash"}]}, {"id": "d1", "choices": [{"message": {"content": "{\"answer\":1}"}}]}, {"id": "d2", "choices": [{"message": {"content": "{\"answer\":2,\"label\":\"ok\"}"}}]}])
    monkeypatch.setattr("cgkn.providers.connectors.deepseek.request.urlopen", lambda req, timeout: Response(next(replies)))
    connector = DeepSeekConnector(PROFILE, environment={"DEEPSEEK_API_KEY": "secret"})
    schema = {"type": "object", "properties": {"answer": {"type": "integer"}, "label": {"type": "string"}}, "required": ["answer", "label"], "additionalProperties": False}
    with pytest.raises(ProviderConnectionError, match="CHANGED_SEMANTICS"):
        connector.complete_structured(system="s", user="u", schema_name="probe", schema=schema, config=ModelRoleConfig("worker", "deepseek", 10, 10))


def test_deepseek_probe_leaves_room_for_reasoning_before_json(monkeypatch) -> None:
    calls = []
    replies = iter([
        {"data": [{"id": "deepseek-flash"}]},
        {"data": [{"id": "deepseek-flash"}]},
        {
            "id": "d1",
            "model": "deepseek-flash",
            "choices": [{"message": {"content": "{\"ok\":true}"}}],
        },
    ])

    def fake(req, timeout):
        calls.append(json.loads(req.data) if req.data else None)
        return Response(next(replies))

    monkeypatch.setattr("cgkn.providers.connectors.deepseek.request.urlopen", fake)
    connector = DeepSeekConnector(
        {**PROFILE, "max_output_tokens": 1000},
        environment={"DEEPSEEK_API_KEY": "secret"},
    )
    health = connector.probe_connection()
    assert health.eligible is True
    assert calls[-1]["max_tokens"] == 256


def test_local_schema_validation_rejects_malformed_and_nonconforming_json() -> None:
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    with pytest.raises(ProviderConnectionError, match="SCHEMA_FAILURE"):
        parse_and_validate("not-json", schema)
    with pytest.raises(ProviderConnectionError, match="SCHEMA_FAILURE"):
        parse_and_validate('{"ok":"yes"}', schema)


def test_vendor_text_and_credential_resolution_are_fail_closed() -> None:
    assert sanitize_vendor_text("token=secret", ["secret"]) == "token=[REDACTED]"
    assert len(sanitize_vendor_text("x" * 1200)) == 1000
    assert resolve_credential({"PRIMARY": " value "}, "PRIMARY", "LEGACY") == ("value", True)
    assert resolve_credential({}, "PRIMARY", "LEGACY") == ("", False)
    with pytest.raises(ProviderConnectionError, match="CONFIG_CONFLICT"):
        resolve_credential({"PRIMARY": "one", "LEGACY": "two"}, "PRIMARY", "LEGACY")

