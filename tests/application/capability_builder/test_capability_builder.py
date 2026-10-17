from __future__ import annotations

import json
from pathlib import Path

import pytest

from cgkn.application.capability_builder import CapabilityBuilderService, CapabilityRisk, CapabilitySpec, CapabilityStore
from cgkn.providers import ModelRoleConfig, ProviderCompletion


class FakeClient:
    def __init__(self, code: str): self.code = code
    def complete(self, **kwargs):
        before = '"""Generated capability candidate."""\n\ndef execute(value):\n    raise NotImplementedError("candidate not implemented")\n'
        action = {"action": "patch_file", "path": "executor.py", "find": before, "replace": self.code}
        node_id = json.loads(kwargs["user"])["node_id"]
        envelope = {"schema_version": "1.0", "node_id": node_id, "summary": "implemented", "actions": [action], "expected_outputs": ["tests pass"], "confidence": 1.0, "needs_escalation": False, "escalation_reason": ""}
        return ProviderCompletion(json.dumps(envelope), {"total_tokens": 10})


def spec() -> CapabilitySpec:
    return CapabilitySpec("text.slugify", "1", "Create URL slugs.", {"type": "string"}, {"type": "string"}, ({"input": "Hello World", "output": "hello-world"},), ("lowercase words joined by hyphens",))


def test_build_admit_execute_and_store(tmp_path: Path):
    code = '"""Generated capability candidate."""\n\nimport re\n\ndef execute(value):\n    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")\n'
    service = CapabilityBuilderService(FakeClient(code), ModelRoleConfig("worker", "grok", 30, 1000, 0, "low"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=CapabilityStore(tmp_path / "store"))
    receipt = service.build(tmp_path / "candidates", spec())
    assert receipt.status == "PASS", receipt
    assert receipt.admitted and receipt.execution_passed and receipt.stored
    assert (tmp_path / "store" / "text-slugify-1" / "admission.json").is_file()


def test_rejects_non_capability_dependencies():
    with pytest.raises(ValueError, match="canonical capability refs"):
        CapabilitySpec("bad", "1", "bad", {}, {}, ({"input": 1, "output": 1},), ("works",), allowed_dependencies=("requests",))


def test_store_rejects_unadmitted_candidate(tmp_path: Path):
    candidate = tmp_path / "candidate"; candidate.mkdir(); (candidate / "admission.json").write_text('{"status":"REJECTED"}')
    from cgkn.application.capability_builder import CapabilityPackage
    with pytest.raises(ValueError, match="admitted"):
        CapabilityStore(tmp_path / "store").put(CapabilityPackage(spec(), str(candidate), "x@1", "x@1", "sha256:x", ("tests/x",)))


def test_generated_network_import_is_rejected(tmp_path: Path):
    code = 'import requests\n\ndef execute(value):\n    return value\n'
    service = CapabilityBuilderService(FakeClient(code), ModelRoleConfig("worker", "grok", 30, 1000, 0, "low"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=CapabilityStore(tmp_path / "store"))
    receipt = service.build(tmp_path / "candidates", CapabilitySpec("unsafe", "1", "unsafe", {}, {}, ({"input": "x", "output": "x"},), ("works",), CapabilityRisk.PURE))
    assert receipt.status == "FAIL"
    assert not receipt.admitted


def test_public_network_candidate_must_use_bounded_runtime(tmp_path: Path):
    code = 'def execute(value, ctx):\n    return {"status_code": 200}\n'
    service = CapabilityBuilderService(FakeClient(code), ModelRoleConfig("worker", "grok", 30, 1000, 0, "low"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=CapabilityStore(tmp_path / "store"))
    network_spec = CapabilitySpec("web.fetch.public", "1", "fetch", {}, {}, ({"input":{"url":"https://example.com"},"output":{"status_code":200},"runtime":{"network_response":{"status_code":200}}},), ("bounded",), CapabilityRisk.READ_ONLY_PUBLIC_NETWORK)
    receipt = service.build(tmp_path / "candidates", network_spec)
    assert receipt.status == "FAIL" and not receipt.admitted


def test_declared_dependency_must_be_invoked(tmp_path: Path):
    code = 'def execute(value, ctx):\n    return value\n'
    service = CapabilityBuilderService(FakeClient(code), ModelRoleConfig("worker", "grok", 30, 1000, 0, "low"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=CapabilityStore(tmp_path / "store"))
    dependent = CapabilitySpec("dependent", "1", "dependent", {}, {}, ({"input":"x","output":"x","runtime":{"dependency_results":{"text.slugify@1":"x"}}},), ("uses dependency",), allowed_dependencies=("text.slugify@1",))
    receipt = service.build(tmp_path / "candidates", dependent)
    assert receipt.status == "FAIL" and not receipt.admitted


def test_runtime_materializes_frozen_json_object_before_candidate_call(tmp_path: Path):
    code = 'def execute(value):\n    return {"is_dict": isinstance(value, dict), "value": value["name"]}\n'
    object_spec = CapabilitySpec("object.echo", "1", "echo object", {}, {}, ({"input":{"name":"ok"},"output":{"is_dict":True,"value":"ok"}},), ("receives JSON object",))
    service = CapabilityBuilderService(FakeClient(code), ModelRoleConfig("worker", "grok", 30, 1000, 0, "low"), provider_id="grok", mode="SINGLE_PROVIDER_MODE", store=CapabilityStore(tmp_path / "store"))
    receipt = service.build(tmp_path / "candidates", object_spec)
    assert receipt.status == "PASS" and receipt.execution_passed and receipt.admitted
