from __future__ import annotations

import json

import pytest

from cgkn.providers import ModelRoleConfig, ProviderConnectionError, QwenConnector


PROFILE = {
    "provider_id": "qwen", "region": "ap-northeast-1", "workspace_id": "ws1",
    "base_url": "https://ws1.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1",
    "catalog_base_url": "https://ws1.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1",
    "preferred_models": ["qwen3.8-max"], "timeout": 10, "max_output_tokens": 100,
}


class Response:
    def __init__(self, value): self.value = value; self.status = 200
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self, _limit): return json.dumps(self.value).encode()


def test_qwen_rejects_credential_conflict() -> None:
    with pytest.raises(ProviderConnectionError, match="CONFIG_CONFLICT"):
        QwenConnector(PROFILE, environment={"CGKN_QWEN_API_KEY": "one", "DASHSCOPE_API_KEY": "two"})


def test_qwen_rejects_region_endpoint_mismatch() -> None:
    bad = {**PROFILE, "region": "ap-southeast-1"}
    with pytest.raises(ProviderConnectionError, match="QWEN_REGION_KEY_MISMATCH"):
        QwenConnector(bad, environment={"CGKN_QWEN_API_KEY": "secret"})


def test_qwen_native_schema_path_is_vendor_local(monkeypatch) -> None:
    calls = []
    replies = iter([
        {"data": [{"id": "qwen3.8-max"}]},
        {"id": "q1", "model": "qwen3.8-max-build", "choices": [{"message": {"content": "{\"ok\":true}"}}], "usage": {"total_tokens": 4}},
    ])
    def fake(req, timeout):
        calls.append((req.full_url, json.loads(req.data) if req.data else None, timeout)); return Response(next(replies))
    monkeypatch.setattr("cgkn.providers.connectors.qwen.request.urlopen", fake)
    connector = QwenConnector(PROFILE, environment={"CGKN_QWEN_API_KEY": "secret"})
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
    result = connector.complete_structured(system="s", user="u", schema_name="probe", schema=schema, config=ModelRoleConfig("worker", "qwen", 10, 10))
    assert result.model == "qwen3.8-max-build"
    payload = calls[-1][1]
    assert payload["response_format"]["json_schema"] == {"name": "probe", "strict": True, "schema": schema}
    assert "/chat/completions" in calls[-1][0]
    assert "secret" not in repr(connector.connection_snapshot().as_dict())


@pytest.mark.parametrize(("status", "code", "expected"), [(401, "InvalidApiKey", "QWEN_INVALID_KEY"), (401, "", "QWEN_AUTH_UNKNOWN"), (403, "WorkspaceDenied", "QWEN_WORKSPACE_UNAUTHORIZED"), (404, "", "QWEN_WORKSPACE_NOT_FOUND")])
def test_qwen_error_classification(status, code, expected) -> None:
    connector = QwenConnector(PROFILE, environment={"CGKN_QWEN_API_KEY": "secret"})
    assert connector.classify_error(http_status=status, vendor_code=code) == expected

