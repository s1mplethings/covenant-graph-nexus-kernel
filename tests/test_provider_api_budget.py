from __future__ import annotations

import json
import pathlib

import pytest

from scripts import provider_api_budget


def _configure(monkeypatch: pytest.MonkeyPatch, ledger: pathlib.Path) -> None:
    values = {
        "CGKN_PROVIDER_BUDGET_LEDGER": str(ledger),
        "CGKN_PROVIDER_MAX_API_CALLS": "1",
        "CGKN_PROVIDER_MAX_INPUT_TOKENS": "100",
        "CGKN_PROVIDER_MAX_OUTPUT_TOKENS": "50",
        "CGKN_PROVIDER_MAX_ESTIMATED_COST": "1.0",
        "CGKN_PROVIDER_INPUT_COST_PER_MILLION": "1.0",
        "CGKN_PROVIDER_OUTPUT_COST_PER_MILLION": "2.0",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


@pytest.mark.live_provider
def test_budget_ledger_reserves_finalizes_and_redacts(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "ledger.json"
    _configure(monkeypatch, ledger)
    reservation = provider_api_budget.reserve_call(
        case_id="CASE_01", purpose="generation", model="model-a",
        request_identity="sha256-only", estimated_input_tokens=20,
        requested_output_tokens=10, retry_count=0,
    )
    provider_api_budget.mark_request_started(reservation)
    provider_api_budget.mark_response_received(
        reservation,
        response={"id": "qwen-response", "usage": {"prompt_tokens": 18, "completion_tokens": 7}},
        http_status=200,
    )
    provider_api_budget.finalize_call(
        reservation, usage={"prompt_tokens": 18, "completion_tokens": 7},
        http_status=200, status="PASS",
    )
    value = json.loads(ledger.read_text(encoding="utf-8"))
    assert value["totals"]["api_calls"] == 1
    assert value["totals"]["input_tokens"] == 18
    assert value["totals"]["output_tokens"] == 7
    assert value["totals"]["completed_calls"] == 1
    assert value["calls"][0]["status"] == "SUCCEEDED"
    assert value["calls"][0]["provider_request_id"] == "qwen-response"
    assert value["contains_credentials"] is False
    assert "api_key" not in ledger.read_text(encoding="utf-8").lower()


def test_budget_is_checked_before_second_transport(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "ledger.json"
    _configure(monkeypatch, ledger)
    provider_api_budget.reserve_call(
        case_id="CASE_01", purpose="generation", model="model-a",
        request_identity="one", estimated_input_tokens=1,
        requested_output_tokens=1, retry_count=0,
    )
    with pytest.raises(provider_api_budget.ProviderBudgetExhausted, match="max_api_calls"):
        provider_api_budget.reserve_call(
            case_id="CASE_02", purpose="generation", model="model-a",
            request_identity="two", estimated_input_tokens=1,
            requested_output_tokens=1, retry_count=0,
        )


def test_response_cache_is_explicit_and_marked_as_replay(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / "cache"
    identity = "a" * 64
    monkeypatch.setenv("CGKN_PROVIDER_RESPONSE_CACHE_DIR", str(cache))
    monkeypatch.setenv("CGKN_PROVIDER_CACHE_MODE", "read_write")
    provider_api_budget.store_cached_response(identity, {"id": "response-1", "output": []})
    envelope = json.loads(next(cache.rglob("*.json")).read_text(encoding="utf-8"))
    assert envelope["call_mode"] == "CACHE_REPLAY"
    assert envelope["contains_credentials"] is False
    monkeypatch.setenv("CGKN_PROVIDER_CACHE_MODE", "replay_only")
    assert provider_api_budget.load_cached_response(identity)["id"] == "response-1"


def test_stale_reserved_call_reconciles_to_cancelled_and_releases_budget(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger.json"
    _configure(monkeypatch, ledger)
    provider_api_budget.reserve_call(
        case_id="CASE_01", purpose="PLANNING", model="qwen3.6-plus",
        request_identity="reserved", estimated_input_tokens=20,
        requested_output_tokens=10, retry_count=0,
    )
    provider_api_budget.reconcile_incomplete_calls(ledger, process_alive=lambda _pid: False)
    value = json.loads(ledger.read_text(encoding="utf-8"))
    assert value["calls"][0]["status"] == "CANCELLED_BEFORE_SEND"
    assert value["totals"]["api_calls"] == 0
    assert value["totals"]["cancelled_before_send_calls"] == 1
    provider_api_budget.reserve_call(
        case_id="CASE_01", purpose="PLANNING", model="qwen3.6-plus",
        request_identity="replacement", estimated_input_tokens=20,
        requested_output_tokens=10, retry_count=0,
    )


def test_started_call_reconciles_to_interrupted_unknown_and_keeps_budget(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger.json"
    _configure(monkeypatch, ledger)
    reservation = provider_api_budget.reserve_call(
        case_id="CASE_01", purpose="GENERATION", model="qwen3.6-plus",
        request_identity="started", estimated_input_tokens=20,
        requested_output_tokens=10, retry_count=0,
    )
    provider_api_budget.mark_request_started(reservation)
    provider_api_budget.reconcile_incomplete_calls(ledger, process_alive=lambda _pid: False)
    value = json.loads(ledger.read_text(encoding="utf-8"))
    call = value["calls"][0]
    assert call["status"] == "INTERRUPTED_UNKNOWN"
    assert call["input_tokens"] == "TOKEN_USAGE_UNAVAILABLE"
    assert call["estimated_cost"] == "PRICE_NOT_AVAILABLE"
    assert value["totals"]["api_calls"] == 1
    assert value["totals"]["unknown_calls"] == 1
    with pytest.raises(provider_api_budget.ProviderBudgetExhausted, match="max_api_calls"):
        provider_api_budget.reserve_call(
            case_id="CASE_01", purpose="GENERATION", model="qwen3.6-plus",
            request_identity="second", estimated_input_tokens=1,
            requested_output_tokens=1, retry_count=0,
        )


def test_purpose_specific_call_budgets_are_enforced(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger.json"
    _configure(monkeypatch, ledger)
    monkeypatch.setenv("CGKN_PROVIDER_MAX_API_CALLS", "4")
    monkeypatch.setenv("CGKN_PROVIDER_MAX_PLANNING_CALLS", "1")
    monkeypatch.setenv("CGKN_PROVIDER_MAX_GENERATION_CALLS", "1")
    monkeypatch.setenv("CGKN_PROVIDER_MAX_REPAIR_CALLS", "2")
    provider_api_budget.reserve_call(
        case_id="CASE_01", purpose="PLANNING", model="qwen3.6-plus",
        request_identity="planning-one", estimated_input_tokens=1,
        requested_output_tokens=1, retry_count=0,
    )
    with pytest.raises(provider_api_budget.ProviderBudgetExhausted, match="max_planning_calls"):
        provider_api_budget.reserve_call(
            case_id="CASE_01", purpose="PLANNING", model="qwen3.6-plus",
            request_identity="planning-two", estimated_input_tokens=1,
            requested_output_tokens=1, retry_count=0,
        )


def test_failure_before_http_send_cancels_reservation(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = tmp_path / "ledger.json"
    _configure(monkeypatch, ledger)
    reservation = provider_api_budget.reserve_call(
        case_id="CASE_01", purpose="GENERATION", model="qwen3.6-plus",
        request_identity="pre-send", estimated_input_tokens=5,
        requested_output_tokens=5, retry_count=0,
    )
    provider_api_budget.finalize_call(
        reservation, usage=None, http_status=None, status="FAILED"
    )
    value = json.loads(ledger.read_text(encoding="utf-8"))
    assert value["calls"][0]["status"] == "CANCELLED_BEFORE_SEND"
    assert value["totals"]["api_calls"] == 0
