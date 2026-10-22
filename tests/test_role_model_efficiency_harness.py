import copy
import json

from cgkn.providers import ModelRoleConfig, ProviderCompletion
from scripts.run_role_model_efficiency import (
    _ControlledPartialCaptureClient,
    _ReplayFirstThenLiveClient,
    _controlled_partial_schema,
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
    assert files["minItems"] == files["maxItems"] == 2
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
