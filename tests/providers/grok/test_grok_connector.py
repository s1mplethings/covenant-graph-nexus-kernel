from __future__ import annotations

import json

import pytest

from cgkn.providers import GrokConnector, ModelRoleConfig, ProviderConnectionError


PROFILE = {"provider_id": "grok", "base_url": "https://api.x.ai/v1", "api_backend": "RESPONSES", "preferred_models": ["grok-4.7"], "reasoning_effort": "medium", "timeout": 10, "max_output_tokens": 100, "prompt_cache_policy": "disabled_for_benchmark"}


class Response:
    def __init__(self, value): self.value = value; self.status = 200
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self, _limit): return json.dumps(self.value).encode()


def test_grok_rejects_management_endpoint_and_credential_conflict() -> None:
    with pytest.raises(ProviderConnectionError, match="GROK_ENDPOINT_ERROR"):
        GrokConnector({**PROFILE, "base_url": "https://management-api.x.ai/v1"}, environment={"XAI_API_KEY": "x"})
    with pytest.raises(ProviderConnectionError, match="CONFIG_CONFLICT"):
        GrokConnector(PROFILE, environment={"CGKN_GROK_API_KEY": "one", "XAI_API_KEY": "two"})


def test_grok_responses_structured_path(monkeypatch) -> None:
    calls = []
    replies = iter([
        {"data": [{"id": "grok-4.7"}]},
        {"id": "r1", "model": "grok-4.7", "status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "{\"ok\":true}"}]}], "usage": {"input_tokens_details": {"cached_tokens": 0}}},
    ])
    def fake(req, timeout): calls.append((req.full_url, json.loads(req.data) if req.data else None)); return Response(next(replies))
    monkeypatch.setattr("cgkn.providers.connectors.grok.request.urlopen", fake)
    connector = GrokConnector(PROFILE, environment={"XAI_API_KEY": "secret"})
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
    result = connector.complete_structured(system="s", user="u", schema_name="probe", schema=schema, config=ModelRoleConfig("worker", "grok", 10, 10, reasoning_effort="low"))
    assert result.text == '{"ok":true}'
    payload = calls[-1][1]
    assert calls[-1][0].endswith("/responses")
    assert payload["text"]["format"] == {"type": "json_schema", "name": "probe", "strict": True, "schema": schema}
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["store"] is False


@pytest.mark.parametrize(("status", "message", "expected"), [(401, "incorrect API key", "GROK_INVALID_API_KEY"), (401, "management key", "GROK_WRONG_KEY_TYPE"), (403, "forbidden", "GROK_FORBIDDEN"), (404, "model missing", "GROK_MODEL_NOT_VISIBLE")])
def test_grok_error_classification(status, message, expected) -> None:
    connector = GrokConnector(PROFILE, environment={"XAI_API_KEY": "secret"})
    assert connector.classify_error(http_status=status, message=message) == expected

