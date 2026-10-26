import copy
import json

from cgkn.providers import ModelRoleConfig, ProviderCompletion
from scripts.run_role_model_efficiency import (
    _ControlledPartialCaptureClient,
    _ReplayFirstThenLiveClient,
    _annotate_tier1_costs,
    _call_cost_cny,
    _controlled_partial_schema,
    _materialization_metrics,
)


SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "properties": {
                "kind": {"const": "file_bundle"},
                "files": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {"path": {"enum": ["a.py", "b.py", "c.py"]}},
                    },
                },
            },
        },
        {"type": "object", "properties": {"kind": {"const": "escalation"}}},
    ]
}


class _Client:
    def __init__(self, completion: ProviderCompletion):
        self.completion = completion
        self.schemas = []

    def complete(self, **kwargs):
        self.schemas.append(copy.deepcopy(kwargs["schema"]))
        return self.completion


def _completion(paths=("a.py", "b.py")) -> ProviderCompletion:
    return ProviderCompletion(
        json.dumps({
            "schema_version": "2.0",
            "kind": "file_bundle",
            "unit_id": "tests",
            "files": [{"path": path, "content": ""} for path in paths],
        }),
        "deepseek-flash",
        "request-1",
        {"prompt_tokens": 10, "completion_tokens": 5},
        1,
        {"final_status": "ACCEPTED"},
        {},
    )


def test_controlled_partial_schema_is_exact_and_does_not_mutate_source():
    original = copy.deepcopy(SCHEMA)
    controlled = _controlled_partial_schema(SCHEMA, ("a.py", "b.py"))
    files = controlled["oneOf"][0]["properties"]["files"]
    assert files["minItems"] == 1
    assert files["maxItems"] == 2
    assert files["items"]["properties"]["path"]["enum"] == ["a.py", "b.py"]
    assert SCHEMA == original


def test_controlled_capture_records_one_real_partial_and_annotates_receipt():
    inner = _Client(_completion())
    capture = _ControlledPartialCaptureClient(inner, ("a.py", "b.py"))
    result = capture.complete(
        system="system", user="user", schema_name="bundle", schema=SCHEMA,
        config=ModelRoleConfig("worker", "deepseek"),
    )
    assert capture.completion == result
    assert len(inner.schemas) == 1
    assert result.selection_receipt["benchmark_control"]["schema_changed_for_capture_only"] is True


def test_controlled_capture_accepts_any_nonempty_subset_of_allowed_paths():
    inner = _Client(_completion(("a.py",)))
    capture = _ControlledPartialCaptureClient(inner, ("a.py", "b.py"))
    result = capture.complete(
        system="system", user="user", schema_name="bundle", schema=SCHEMA,
        config=ModelRoleConfig("worker", "deepseek"),
    )
    assert json.loads(result.text)["files"][0]["path"] == "a.py"


def test_replay_first_then_live_uses_capture_once():
    captured = _completion()
    live_completion = _completion(("c.py",))
    live = _Client(live_completion)
    replay = _ReplayFirstThenLiveClient(captured, live)
    kwargs = {
        "system": "system", "user": "user", "schema_name": "bundle", "schema": SCHEMA,
        "config": ModelRoleConfig("worker", "deepseek"),
    }
    assert replay.complete(**kwargs) is captured
    assert replay.complete(**kwargs) is live_completion
    assert len(live.schemas) == 1


def test_materialization_metrics_count_discarded_partial_as_duplicate_work():
    first = {
        "call_class": "GENERATION",
        "requested_paths": ["a.py", "b.py", "c.py"],
        "returned_paths": ["a.py", "b.py"],
        "returned_bytes_by_path": {"a.py": 10, "b.py": 10},
        "prompt_tokens": 30,
        "completion_tokens": 20,
        "cached_tokens": 0,
    }
    full_retry = first | {
        "call_class": "GENERATION_RETRY",
        "returned_paths": ["a.py", "b.py", "c.py"],
        "returned_bytes_by_path": {"a.py": 10, "b.py": 10, "c.py": 10},
        "completion_tokens": 30,
    }
    continuation = first | {
        "call_class": "GENERATION_CONTINUATION",
        "requested_paths": ["c.py"],
        "returned_paths": ["c.py"],
        "returned_bytes_by_path": {"c.py": 10},
        "completion_tokens": 10,
    }
    retry_metrics = _materialization_metrics(
        [first, full_retry], final_file_count=3, success=True, pricing=None,
    )
    continuation_metrics = _materialization_metrics(
        [first, continuation], final_file_count=3, success=True, pricing=None,
    )
    assert retry_metrics["repeated_file_output_tokens"] == 20
    assert retry_metrics["repeated_context_tokens"] == 20
    assert retry_metrics["duplicate_generation_token_waste"] == 40
    assert continuation_metrics["duplicate_generation_token_waste"] == 0


def test_tier1_costs_use_official_prices_and_do_not_double_count_reasoning():
    catalog = {
        "snapshot_hash": "sha256:snapshot",
        "index": {"cross_currency": {"usd_cny": 7.0}},
        "models": {
            "qwen": {
                "model": "qwen3.8-max", "currency": "CNY",
                "input_price_per_million": 12, "cached_input_price_per_million": 1.5,
                "output_price_per_million": 36,
            },
            "deepseek": {
                "model": "deepseek-flash", "currency": "USD",
                "input_price_per_million": 0.15, "cached_input_price_per_million": 0.003,
                "output_price_per_million": 0.6,
            },
        },
    }
    qwen_call = {
        "provider": "qwen", "prompt_tokens": 1000, "cached_tokens": 200,
        "completion_tokens": 100, "reasoning_tokens": 25, "total_tokens": 1100,
        "result": "SUCCEEDED", "call_class": "GENERATION",
    }
    deepseek_call = {
        "provider": "deepseek", "prompt_tokens": 1000, "cached_tokens": 0,
        "completion_tokens": 100, "reasoning_tokens": None, "total_tokens": 1100,
        "result": "SUCCEEDED", "call_class": "GENERATION_CONTINUATION",
    }
    assert _call_cost_cny(qwen_call, catalog)["cost_cny"] == 0.0135
    assert _call_cost_cny(deepseek_call, catalog)["cost_cny"] == 0.00147
    row = {"calls": [qwen_call, deepseek_call]}
    _annotate_tier1_costs(row, catalog, strong="qwen", cheap="deepseek")
    assert row["efficiency_metrics"]["cost_evaluated"] is True
    assert row["efficiency_metrics"]["strong_worker_tokens"] == 1100
    assert row["efficiency_metrics"]["cheap_worker_tokens"] == 1100
    assert row["efficiency_metrics"]["continuation_calls"] == 1


def test_tier1_costs_read_nested_coordinator_usage_and_infer_strong_provider():
    catalog = {
        "snapshot_hash": "sha256:snapshot",
        "index": {"cross_currency": {"usd_cny": 7.0}},
        "models": {
            "qwen": {
                "model": "qwen3.8-max", "currency": "CNY",
                "input_price_per_million": 12, "cached_input_price_per_million": 1.5,
                "output_price_per_million": 36,
            },
        },
    }
    row = {"provider_ledger": {"calls": {
        "coordinator_design": [{
            "model": "qwen3.8-max", "usage": {
                "prompt_tokens": 1000, "cached_tokens": 200,
                "completion_tokens": 100, "total_tokens": 1100,
            },
        }],
        "coordinator_attribution": [],
        "worker": [],
    }}}
    _annotate_tier1_costs(row, catalog, strong="qwen", cheap="deepseek")
    assert row["efficiency_metrics"]["cost_evaluated"] is True
    assert row["efficiency_metrics"]["coordinator_tokens"] == 1100
    assert row["efficiency_metrics"]["cost_cny"] == 0.0135
    assert row["efficiency_metrics"]["failed_call_cost_cny"] == 0
