from __future__ import annotations

import json

import pytest

from cgkn.application.self_growth import StrongDecisionPacket
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from experiments.self_growth_v1.providers import (
    ProviderStrongDecider,
    RecordingCompletionClient,
    model_call_evidence,
)


class FakeClient:
    def __init__(self, completion=None, error=None):
        self.completion, self.error, self.requests = completion, error, []

    def complete(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        return self.completion


def packet() -> StrongDecisionPacket:
    return StrongDecisionPacket(
        {"goal": "normalize records"},
        {"gap_class": "CAPABILITY_GAP"},
        ({"capability_ref": "records.filter@1"},),
        ({"reason": "no compatible composition"},),
        "normalized records",
        "LOW",
        ("general records.normalize", "task-specific transform"),
        ("stdlib_only", "sandbox_only"),
        5000,
    )


def test_strong_decider_sends_only_compressed_packet() -> None:
    completion = ProviderCompletion(
        json.dumps({"decision": "GENERAL_FAMILY", "reason_codes": ["REUSABLE_BOUNDARY"]}),
        "qwen-real",
        "req-1",
        {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
        1,
        {"final_status": "ACCEPTED"},
    )
    client = FakeClient(completion)
    result = ProviderStrongDecider(client, ModelRoleConfig("agent", "qwen")).decide(packet())
    assert result.decision == "GENERAL_FAMILY"
    request = client.requests[0]
    assert json.loads(request["user"]) == packet().as_dict()
    assert "hidden" not in request["user"].lower()
    assert result.call.total_tokens == 14
    assert result.call.role == "strong"
    assert result.call.selection_receipt_hash.startswith("sha256:")


def test_recording_client_preserves_failure_with_unknown_usage() -> None:
    recorder = RecordingCompletionClient(FakeClient(error=TimeoutError("provider timed out")))
    with pytest.raises(TimeoutError):
        recorder.complete(system="s", user="u", schema_name="x", schema={"type": "object"}, config=ModelRoleConfig("worker", "deepseek"))
    call = model_call_evidence(recorder.records[0])
    assert call.status == "FAIL"
    assert call.total_tokens is None
    assert call.usage_status == "UNKNOWN_AFTER_TRANSPORT_FAILURE"


def test_model_call_usage_remains_null_when_provider_omits_usage() -> None:
    recorder = RecordingCompletionClient(FakeClient(ProviderCompletion("{}", "deepseek")))
    recorder.complete(system="s", user="u", schema_name="x", schema={"type": "object"}, config=ModelRoleConfig("worker", "deepseek"))
    call = model_call_evidence(recorder.records[0])
    assert call.total_tokens is None
    assert call.usage_status == "UNREPORTED"
