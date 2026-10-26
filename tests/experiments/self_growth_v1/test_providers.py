from __future__ import annotations

import json

import pytest

from cgkn.application.self_growth import GapClass, GrowthClassification, StrongDecisionPacket, proposal_for_need
from cgkn.providers import ModelRoleConfig, ProviderCompletion
from experiments.self_growth_v1.cases import ordered_task_stream
from experiments.self_growth_v1.providers import (
    ProviderCandidateBackend,
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


def test_candidate_builder_exception_preserves_provider_call_evidence(tmp_path) -> None:
    completion = ProviderCompletion(
        "{}",
        "deepseek-flash",
        "req-failed-build",
        {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
        1,
        {"final_status": "ACCEPTED"},
    )
    backend = ProviderCandidateBackend(
        FakeClient(completion),
        ModelRoleConfig("worker", "deepseek"),
        tmp_path / "store",
    )

    class FailingBuilder:
        def build(self, candidate_root, spec):
            del candidate_root, spec
            backend.recorder.complete(
                system="bounded candidate",
                user="public contract",
                schema_name="candidate",
                schema={"type": "object"},
                config=ModelRoleConfig("worker", "deepseek", operation="GENERATION"),
            )
            raise RuntimeError("synthetic post-provider failure")

    backend.builder = FailingBuilder()
    case = ordered_task_stream()[10]
    classification = GrowthClassification(GapClass.CAPABILITY_GAP, ("NO_MATCH",), True)
    proposal = proposal_for_need(case.need, classification, generalized=True)

    result = backend.build(proposal, case, tmp_path / "candidate")

    assert result.status == "FAIL"
    assert result.error == "CANDIDATE_BUILD_EXCEPTION:RuntimeError"
    assert result.qualification.status == "FAIL"
    assert len(result.calls) == 1
    assert result.calls[0].request_id == "req-failed-build"
    assert result.calls[0].total_tokens == 14
