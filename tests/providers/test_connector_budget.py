from __future__ import annotations

import json

import pytest

from cgkn.providers import (
    ConnectorCompletionClient,
    ModelRoleConfig,
    ProviderCompletion,
    ProviderConnectorRegistry,
)
from scripts import provider_api_budget


pytestmark = [
    pytest.mark.happy_path,
    pytest.mark.negative,
    pytest.mark.boundary,
    pytest.mark.fault_injection,
    pytest.mark.security,
]


class FakeConnector:
    provider_id = "fake"

    def complete_structured(self, **kwargs):
        return ProviderCompletion(
            '{"ok":true}',
            "fake-model",
            "request-1",
            {"input_tokens": 7, "output_tokens": 3},
        )


class FailingConnector:
    provider_id = "fake"

    def complete_structured(self, **kwargs):
        raise RuntimeError("HTTP 503 sanitized failure")


def _budget(monkeypatch, ledger):
    values = {
        "CGKN_PROVIDER_BUDGET_LEDGER": str(ledger),
        "CGKN_PROVIDER_MAX_API_CALLS": "2",
        "CGKN_PROVIDER_MAX_BENCHMARK_CALLS": "2",
        "CGKN_PROVIDER_MAX_INPUT_TOKENS": "100",
        "CGKN_PROVIDER_MAX_OUTPUT_TOKENS": "100",
        "CGKN_PROVIDER_MAX_ESTIMATED_COST": "1",
        "CGKN_PROVIDER_INPUT_COST_PER_MILLION": "2",
        "CGKN_PROVIDER_OUTPUT_COST_PER_MILLION": "6",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def _config() -> ModelRoleConfig:
    return ModelRoleConfig("worker", "fake", 30, 10, 0, "none")


def test_connector_client_records_live_call_in_budget_ledger(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    _budget(monkeypatch, ledger)
    client = ConnectorCompletionClient(
        ProviderConnectorRegistry((FakeConnector(),)),
        enforce_budget=True,
        budget_purpose="BENCHMARK",
        run_id="run-1",
        case_id="case",
    )
    client.complete(system="s", user="u", schema_name="x", schema={"type": "object"}, config=_config())
    value = json.loads(ledger.read_text(encoding="utf-8"))
    assert value["totals"]["api_calls"] == 1
    assert value["totals"]["input_tokens"] == 7
    assert value["totals"]["output_tokens"] == 3
    assert value["calls"][0]["purpose"] == "BENCHMARK"
    assert value["calls"][0]["status"] == "SUCCEEDED"


def test_budget_enforcement_fails_closed_without_rates(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    _budget(monkeypatch, ledger)
    monkeypatch.delenv("CGKN_PROVIDER_OUTPUT_COST_PER_MILLION")
    client = ConnectorCompletionClient(
        ProviderConnectorRegistry((FakeConnector(),)),
        enforce_budget=True,
        budget_purpose="BENCHMARK",
    )
    with pytest.raises(provider_api_budget.ProviderBudgetExhausted, match="price estimates"):
        client.complete(system="s", user="u", schema_name="x", schema={"type": "object"}, config=_config())


def test_failed_connector_call_is_reconciled_without_secret_text(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    _budget(monkeypatch, ledger)
    client = ConnectorCompletionClient(
        ProviderConnectorRegistry((FailingConnector(),)),
        enforce_budget=True,
        budget_purpose="BENCHMARK",
    )
    with pytest.raises(RuntimeError, match="sanitized"):
        client.complete(system="s", user="u", schema_name="x", schema={"type": "object"}, config=_config())
    call = json.loads(ledger.read_text(encoding="utf-8"))["calls"][0]
    assert call["status"] == "FAILED"
    assert call["http_status"] == 503


def test_connector_client_without_budget_uses_registry_and_skips_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("CGKN_PROVIDER_BUDGET_LEDGER", str(tmp_path / "unused.json"))
    client = ConnectorCompletionClient(ProviderConnectorRegistry((FakeConnector(),)))
    result = client.complete(
        system="s", user="u", schema_name="x", schema={"type": "object"}, config=_config()
    )
    assert result.request_id == "request-1"
    assert not (tmp_path / "unused.json").exists()
