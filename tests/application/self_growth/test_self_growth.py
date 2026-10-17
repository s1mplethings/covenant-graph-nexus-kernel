from __future__ import annotations

import json

from cgkn.application.capability_builder import CapabilityBuilderService, CapabilitySpec, CapabilityStore
from cgkn.application.self_growth import SelfGrowthService
from cgkn.providers import ModelRoleConfig, ProviderCompletion


class CountingClient:
    calls = 0
    def complete(self, **kwargs):
        self.calls += 1
        prompt = json.loads(kwargs["user"]); before = prompt["current_sources"]["executor.py"]
        code = 'def execute(value):\n    return value.lower().replace(" ", "-")\n'
        value = {"schema_version":"1.0","node_id":prompt["node_id"],"summary":"done","actions":[{"action":"patch_file","path":"executor.py","find":before,"replace":code}],"expected_outputs":["tests pass"],"confidence":1.0,"needs_escalation":False,"escalation_reason":""}
        return ProviderCompletion(json.dumps(value), {"total_tokens": 12})


def test_growth_build_resume_then_reuse_without_builder(tmp_path):
    spec = CapabilitySpec("text.slugify", "1", "slugify", {}, {}, ({"input":"Hello World","output":"hello-world"},), ("works",))
    client = CountingClient(); store = CapabilityStore(tmp_path / "store")
    builder = CapabilityBuilderService(client, ModelRoleConfig("worker","grok",30,1000,0,"low"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=store)
    growth = SelfGrowthService(builder, store, provider_id="grok", mode="SINGLE_PROVIDER_MODE", history_path=tmp_path / "history.json")
    first = growth.ensure_and_resume(tmp_path / "candidates", spec, "Hello World")
    assert first.status == "PASS" and first.growth_invoked and first.builder_invoked and first.output == "hello-world"
    second = growth.ensure_and_resume(tmp_path / "unused", spec, "Again Now")
    assert second.status == "PASS" and second.reused and not second.growth_invoked and not second.builder_invoked
    assert second.provider_calls == 0 and second.output == "again-now" and client.calls == 1
    assert len(json.loads((tmp_path / "history.json").read_text())["events"]) == 1


def test_growth_classifies_builder_failure(tmp_path):
    spec = CapabilitySpec("text.slugify", "1", "slugify", {}, {}, ({"input":"Hello World","output":"different"},), ("works",))
    client = CountingClient(); store = CapabilityStore(tmp_path / "store")
    builder = CapabilityBuilderService(client, ModelRoleConfig("worker","grok",30,1000,0,"low"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=store)
    outcome = SelfGrowthService(builder, store, provider_id="grok", mode="SINGLE_PROVIDER_MODE", history_path=tmp_path / "history.json").ensure_and_resume(tmp_path / "candidates", spec, "x")
    assert outcome.status == "FAIL" and outcome.failure_class == "BUILD_FAILED" and not outcome.admitted


def test_capability_spec_rejects_unsafe_risk():
    try:
        CapabilitySpec("unsafe", "1", "unsafe", {}, {}, ({"input":1,"output":1},), ("works",), risk="NETWORK_WRITE")
    except ValueError as exc:
        assert "PURE" in str(exc)
    else:
        raise AssertionError("unsafe risk was accepted")
