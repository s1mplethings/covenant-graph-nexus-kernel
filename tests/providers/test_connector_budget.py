from __future__ import annotations

import json

import pytest

from cgkn.providers import ConnectorCompletionClient, GrokConnector, ModelRoleConfig, ProviderCompletion, ProviderConnectionError, ProviderConnectorRegistry
from scripts import provider_api_budget

pytestmark = [pytest.mark.happy_path, pytest.mark.negative, pytest.mark.boundary, pytest.mark.fault_injection, pytest.mark.security]


class FakeConnector:
    provider_id = "fake"
    def complete_structured(self, **kwargs):
        return ProviderCompletion('{"ok":true}', "fake-model", "request-1", {"input_tokens": 7, "output_tokens": 3})


class FailingConnector:
    provider_id = "fake"
    def complete_structured(self, **kwargs):
        raise RuntimeError("HTTP 503 sanitized failure")


class TimeoutConnector:
    provider_id = "fake"
    def complete_structured(self, **kwargs):
        raise ProviderConnectionError("PROVIDER_CONNECT_OR_HEADER_TIMEOUT","timed out",outcome_unknown=True,timeout_phase="CONNECT_OR_HEADER_TIMEOUT",evidence={"requested_timeout_seconds":180,"effective_timeout_seconds":180,"provider_default_timeout_seconds":120,"provider_max_timeout_seconds":240,"elapsed_ms":180001})


def _budget(monkeypatch, ledger):
    values = {"CGKN_PROVIDER_BUDGET_LEDGER":str(ledger),"CGKN_PROVIDER_MAX_API_CALLS":"2","CGKN_PROVIDER_MAX_INPUT_TOKENS":"100","CGKN_PROVIDER_MAX_OUTPUT_TOKENS":"100","CGKN_PROVIDER_MAX_ESTIMATED_COST":"1","CGKN_PROVIDER_INPUT_COST_PER_MILLION":"2","CGKN_PROVIDER_OUTPUT_COST_PER_MILLION":"6","CGKN_PROVIDER_MAX_CAPABILITY_BUILD_CALLS":"2"}
    for key, value in values.items(): monkeypatch.setenv(key, value)


def test_connector_client_records_live_call_in_budget_ledger(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"; _budget(monkeypatch, ledger)
    client = ConnectorCompletionClient(ProviderConnectorRegistry((FakeConnector(),)), enforce_budget=True, budget_purpose="CAPABILITY_BUILD", run_id="run-1", case_id="case")
    client.complete(system="s", user="u", schema_name="x", schema={"type":"object"}, config=ModelRoleConfig("worker","fake",30,10,0,"none"))
    value = json.loads(ledger.read_text(encoding="utf-8"))
    assert value["totals"]["api_calls"] == 1 and value["totals"]["input_tokens"] == 7 and value["totals"]["output_tokens"] == 3
    assert value["calls"][0]["purpose"] == "CAPABILITY_BUILD" and value["calls"][0]["status"] == "SUCCEEDED"


def test_budget_enforcement_fails_closed_without_rates(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"; _budget(monkeypatch, ledger); monkeypatch.delenv("CGKN_PROVIDER_OUTPUT_COST_PER_MILLION")
    client = ConnectorCompletionClient(ProviderConnectorRegistry((FakeConnector(),)), enforce_budget=True)
    with pytest.raises(provider_api_budget.ProviderBudgetExhausted, match="price estimates"):
        client.complete(system="s", user="u", schema_name="x", schema={"type":"object"}, config=ModelRoleConfig("worker","fake",30,10,0,"none"))


def test_connector_client_no_budget_and_failed_transport_paths(tmp_path, monkeypatch):
    config = ModelRoleConfig("worker","fake",30,10,0,"none")
    unbudgeted = ConnectorCompletionClient(ProviderConnectorRegistry((FakeConnector(),)))
    assert unbudgeted.complete(system="s", user="u", schema_name="x", schema={"type":"object"}, config=config).request_id == "request-1"
    ledger = tmp_path / "ledger.json"; _budget(monkeypatch, ledger)
    failing = ConnectorCompletionClient(ProviderConnectorRegistry((FailingConnector(),)), enforce_budget=True)
    with pytest.raises(RuntimeError, match="sanitized"):
        failing.complete(system="s", user="u", schema_name="x", schema={"type":"object"}, config=config)
    call = json.loads(ledger.read_text(encoding="utf-8"))["calls"][0]
    assert call["status"] == "FAILED" and call["http_status"] == 503


def test_timeout_is_finalized_once_with_evidence(tmp_path, monkeypatch):
    ledger=tmp_path / "ledger.json"; _budget(monkeypatch,ledger)
    client=ConnectorCompletionClient(ProviderConnectorRegistry((TimeoutConnector(),)),enforce_budget=True,budget_purpose="CAPABILITY_BUILD")
    with pytest.raises(ProviderConnectionError,match="PROVIDER_CONNECT_OR_HEADER_TIMEOUT"):
        client.complete(system="s",user="u",schema_name="x",schema={"type":"object"},config=ModelRoleConfig("worker","fake",180,10,0,"medium"))
    value=json.loads(ledger.read_text(encoding="utf-8"))
    assert value["totals"]["api_calls"] == 1 and len(value["calls"]) == 1
    call=value["calls"][0]
    assert call["status"] == "FAILED" and call["error_class"] == "PROVIDER_CONNECT_OR_HEADER_TIMEOUT"
    assert call["outcome_unknown"] is True and call["effective_timeout_seconds"] == 180


def test_grok_completion_ledger_has_one_data_plane_call_and_no_catalog(tmp_path,monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self,*_args): return False
        def read(self,_limit): return json.dumps({"id":"r1","model":"grok-4.7","output_text":"{\"ok\":true}","usage":{"input_tokens":2,"output_tokens":1}}).encode()
    urls=[]
    monkeypatch.setattr("cgkn.providers.connectors.grok.request.urlopen",lambda req,timeout:(urls.append(req.full_url) or Response()))
    ledger=tmp_path / "ledger.json"; _budget(monkeypatch,ledger)
    profile={"base_url":"https://api.x.ai/v1","api_backend":"RESPONSES","preferred_models":["grok-4.7"],"default_timeout_seconds":120,"max_timeout_seconds":240}
    connector=GrokConnector(profile,environment={"XAI_API_KEY":"secret"})
    client=ConnectorCompletionClient(ProviderConnectorRegistry((connector,)),enforce_budget=True,budget_purpose="CAPABILITY_BUILD")
    schema={"type":"object","properties":{"ok":{"type":"boolean"}},"required":["ok"],"additionalProperties":False}
    client.complete(system="s",user="u",schema_name="x",schema=schema,config=ModelRoleConfig("worker","grok",180,10,0,"medium"))
    value=json.loads(ledger.read_text(encoding="utf-8"))
    assert len(urls) == len(value["calls"]) == value["totals"]["api_calls"] == 1
    assert urls[0].endswith("/responses") and value["calls"][0]["operation"] == "STRUCTURED_COMPLETION"
