from __future__ import annotations

import json

import pytest

from cgkn.providers import ConnectorCompletionClient, ModelRoleConfig, ProviderCompletion, ProviderConnectorRegistry
from scripts import provider_api_budget

pytestmark = [pytest.mark.happy_path, pytest.mark.negative, pytest.mark.boundary, pytest.mark.fault_injection, pytest.mark.security]


class FakeConnector:
    provider_id = "fake"
    def complete_structured(self, **kwargs):
        return ProviderCompletion('{"ok":true}', "fake-model", "request-1", {"input_tokens": 7, "output_tokens": 3})


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
