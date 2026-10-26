from __future__ import annotations

import json

import pytest

from cgkn.providers import GrokConnector, ModelRoleConfig, ProviderConnectionError
from cgkn.providers.connectors.grok import resolve_effective_timeout

pytestmark = [pytest.mark.happy_path, pytest.mark.negative, pytest.mark.boundary, pytest.mark.fault_injection, pytest.mark.security]


PROFILE = {"provider_id": "grok", "base_url": "https://api.x.ai/v1", "api_backend": "RESPONSES", "preferred_models": ["grok-4.7"], "reasoning_effort": "medium", "timeout": 10, "max_output_tokens": 100, "prompt_cache_policy": "disabled_for_benchmark"}
MODERN_PROFILE = {**{key: value for key, value in PROFILE.items() if key != "timeout"}, "default_timeout_seconds": 120, "max_timeout_seconds": 240}


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
    reply = {"id": "r1", "model": "grok-4.7", "status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "{\"ok\":true}"}]}], "usage": {"input_tokens_details": {"cached_tokens": 0}}}
    def fake(req, timeout): calls.append((req.full_url, json.loads(req.data) if req.data else None, timeout)); return Response(reply)
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
    assert len(calls) == 1 and all(not url.endswith("/models") for url,_,_ in calls)
    assert result.usage["operation"] == "STRUCTURED_COMPLETION" and result.usage["endpoint_class"] == "DATA_PLANE"


def test_legacy_timeout_loads_as_default() -> None:
    connector = GrokConnector(PROFILE, environment={"XAI_API_KEY":"secret"})
    assert connector.default_timeout_seconds == connector.max_timeout_seconds == 10


def test_conflicting_and_invalid_timeout_profiles_are_rejected() -> None:
    with pytest.raises(ProviderConnectionError, match="CONFIG_CONFLICT"):
        GrokConnector({**MODERN_PROFILE,"timeout":10},environment={"XAI_API_KEY":"secret"})
    with pytest.raises(ProviderConnectionError, match="GROK_TIMEOUT_CONFIG_INVALID"):
        GrokConnector({**MODERN_PROFILE,"default_timeout_seconds":241},environment={"XAI_API_KEY":"secret"})
    with pytest.raises(ProviderConnectionError, match="GROK_TIMEOUT_CONFIG_INVALID"):
        GrokConnector({**MODERN_PROFILE,"max_timeout_seconds":601},environment={"XAI_API_KEY":"secret"})


def test_effective_timeout_resolution() -> None:
    assert resolve_effective_timeout(180,120,240) == 180
    assert resolve_effective_timeout(300,120,240) == 240
    assert resolve_effective_timeout(None,120,240) == 120
    assert resolve_effective_timeout(0,120,240) == 120


def test_completion_uses_effective_timeout_and_catalog_uses_default(monkeypatch) -> None:
    calls = []
    replies = iter([
        {"id":"r1","model":"grok-4.7","output_text":"{\"ok\":true}","usage":{"input_tokens":2,"output_tokens":1}},
        {"data":[{"id":"grok-4.7"}]},
    ])
    def fake(req, timeout): calls.append((req.full_url,timeout)); return Response(next(replies))
    monkeypatch.setattr("cgkn.providers.connectors.grok.request.urlopen",fake)
    connector = GrokConnector(MODERN_PROFILE,environment={"XAI_API_KEY":"secret"})
    schema={"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":False}
    completion=connector.complete_structured(system="s",user="u",schema_name="x",schema=schema,config=ModelRoleConfig("worker","grok",180,10,0,"medium"))
    connector.list_models()
    assert calls[0][1] <= 300 and calls[1][1] <= 90
    assert completion.usage["requested_timeout_seconds"] == completion.usage["effective_timeout_seconds"] == 180
    assert completion.usage["provider_default_timeout_seconds"] == 120
    assert completion.usage["provider_max_timeout_seconds"] == 240
    assert completion.usage["elapsed_ms"] >= 0


def test_timeout_before_headers_is_classified(monkeypatch) -> None:
    monkeypatch.setattr("cgkn.providers.connectors.grok.request.urlopen",lambda *_args,**_kwargs: (_ for _ in ()).throw(TimeoutError("timed out")))
    connector=GrokConnector(MODERN_PROFILE,environment={"XAI_API_KEY":"secret"})
    with pytest.raises(ProviderConnectionError) as caught:
        connector._request_json("POST","https://api.x.ai/v1/responses",{},timeout_seconds=180,requested_timeout_seconds=180,operation="STRUCTURED_COMPLETION",endpoint_class="DATA_PLANE")
    assert caught.value.error_class == "PROVIDER_FIRST_PROGRESS_TIMEOUT"
    assert caught.value.timeout_phase == "FIRST_PROGRESS" and caught.value.outcome_unknown
    assert caught.value.evidence["effective_timeout_seconds"] == 180


def test_timeout_during_response_read_is_classified(monkeypatch) -> None:
    class SlowResponse(Response):
        def read(self,_limit): raise TimeoutError("timed out")
    monkeypatch.setattr("cgkn.providers.connectors.grok.request.urlopen",lambda *_args,**_kwargs: SlowResponse({}))
    connector=GrokConnector(MODERN_PROFILE,environment={"XAI_API_KEY":"secret"})
    with pytest.raises(ProviderConnectionError) as caught:
        connector._request_json("POST","https://api.x.ai/v1/responses",{},timeout_seconds=180,requested_timeout_seconds=180,operation="STRUCTURED_COMPLETION",endpoint_class="DATA_PLANE")
    assert caught.value.error_class == "PROVIDER_IDLE_TIMEOUT"
    assert caught.value.timeout_phase == "IDLE_PROGRESS" and caught.value.outcome_unknown


@pytest.mark.parametrize(("status", "message", "expected"), [(401, "incorrect API key", "GROK_INVALID_API_KEY"), (401, "management key", "GROK_WRONG_KEY_TYPE"), (403, "forbidden", "GROK_FORBIDDEN"), (404, "model missing", "GROK_MODEL_NOT_VISIBLE")])
def test_grok_error_classification(status, message, expected) -> None:
    connector = GrokConnector(PROFILE, environment={"XAI_API_KEY": "secret"})
    assert connector.classify_error(http_status=status, message=message) == expected


def test_profile_and_explicit_allowed_model_bind_without_catalog(monkeypatch) -> None:
    connector=GrokConnector({**MODERN_PROFILE,"allowed_models":["grok-4.7-fast"]},environment={"XAI_API_KEY":"secret"})
    monkeypatch.setattr(connector,"list_models",lambda: (_ for _ in ()).throw(AssertionError("catalog called")))
    assert connector.resolve_pinned_model("grok").bound_model == "grok-4.7"
    assert connector.resolve_pinned_model("grok-4.7-fast").bound_model == "grok-4.7-fast"
    with pytest.raises(ProviderConnectionError,match="GROK_MODEL_NOT_ALLOWED"):
        connector.resolve_pinned_model("unknown-model")


def test_catalog_transport_failure_does_not_block_data_plane(monkeypatch) -> None:
    calls=[]
    def fake(req,timeout):
        calls.append(req.full_url)
        if req.full_url.endswith("/models"): raise OSError("catalog unavailable")
        return Response({"id":"r1","model":"grok-4.7","output_text":"{\"ok\":true}","usage":{}})
    monkeypatch.setattr("cgkn.providers.connectors.grok.request.urlopen",fake)
    connector=GrokConnector(MODERN_PROFILE,environment={"XAI_API_KEY":"secret"})
    with pytest.raises(ProviderConnectionError) as caught: connector.list_models()
    assert caught.value.error_class == "PROVIDER_CATALOG_TRANSPORT_FAILURE"
    schema={"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":False}
    completion=connector.complete_structured(system="s",user="u",schema_name="x",schema=schema,config=ModelRoleConfig("worker","grok",180,10,0,"medium"))
    assert completion.usage["catalog_status"] == "DEGRADED_TRANSPORT" and completion.usage["data_plane_status"] == "PASS"
    assert calls[-1].endswith("/responses")


def test_probe_connection_reports_ready_with_catalog_degraded(monkeypatch) -> None:
    def fake(req,timeout):
        if req.full_url.endswith("/models"): raise OSError("catalog unavailable")
        return Response({"id":"r1","model":"grok-4.7","output_text":"{\"ok\":true}","usage":{}})
    monkeypatch.setattr("cgkn.providers.connectors.grok.request.urlopen",fake)
    health=GrokConnector(MODERN_PROFILE,environment={"XAI_API_KEY":"secret"}).probe_connection()
    assert health.eligible and health.catalog_status == "DEGRADED_TRANSPORT" and health.structured_output_status == "PASS"


def test_response_alias_and_actual_model_are_recorded(monkeypatch) -> None:
    monkeypatch.setattr("cgkn.providers.connectors.grok.request.urlopen",lambda req,timeout: Response({"id":"r1","model":"grok-4.7-20261018","output_text":"{\"ok\":true}","usage":{}}))
    connector=GrokConnector(MODERN_PROFILE,environment={"XAI_API_KEY":"secret"})
    schema={"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":False}
    result=connector.complete_structured(system="s",user="u",schema_name="x",schema=schema,config=ModelRoleConfig("worker","grok",180,10,0,"medium"))
    assert result.model == "grok-4.7-20261018" and result.usage["actual_model"] == result.model
    assert result.usage["model_binding_status"] == "RESPONSE_MODEL_ALIAS" and result.usage["binding_source"] == "RESPONSE_CONFIRMED"


def test_response_model_outside_binding_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr("cgkn.providers.connectors.grok.request.urlopen",lambda req,timeout: Response({"id":"r1","model":"unrelated-model","output_text":"{\"ok\":true}","usage":{}}))
    connector=GrokConnector(MODERN_PROFILE,environment={"XAI_API_KEY":"secret"})
    schema={"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":False}
    with pytest.raises(ProviderConnectionError,match="MODEL_BINDING_MISMATCH"):
        connector.complete_structured(system="s",user="u",schema_name="x",schema=schema,config=ModelRoleConfig("worker","grok",180,10,0,"medium"))


def test_data_plane_only_probe_never_touches_catalog(monkeypatch) -> None:
    urls=[]
    def fake(req,timeout): urls.append(req.full_url); return Response({"id":"r1","model":"grok-4.7","output_text":"{\"ok\":true}","usage":{}})
    monkeypatch.setattr("cgkn.providers.connectors.grok.request.urlopen",fake)
    health=GrokConnector(MODERN_PROFILE,environment={"XAI_API_KEY":"secret"}).probe_data_plane_only()
    assert health.eligible and len(urls) == 1 and urls[0].endswith("/responses")

