from __future__ import annotations

import pytest

from cgkn.capabilities import CapabilityDescriptor, CapabilityRegistry
from cgkn.component import ComponentSpec, PortSpec


def setup_registry():
    component = ComponentSpec("json.parse", "1", (PortSpec("text", "artifact.text@1"),), (PortSpec("object", "artifact.json@1"),))
    registry = CapabilityRegistry({component.ref: component})
    descriptor = CapabilityDescriptor("json.parse", "1", component.ref, "python.stdlib.json@1", ("python",), ("text",), ("object",), (), 5, "zero", "LOW", "stdlib", {"module": "json"}, ("tests/json_parse",))
    return registry, descriptor, component


def test_candidate_admission_query_evidence_and_persistence(tmp_path) -> None:
    registry, descriptor, component = setup_registry()
    registry.register_candidate(descriptor)
    registry.admit(descriptor.ref)
    registry.record_execution_evidence(descriptor.ref, True)
    assert registry.resolve("json.parse").observed_success == 1
    assert registry.query(input_port="text") == (descriptor,)
    path = tmp_path / "registry.json"
    registry.save(path)
    loaded = CapabilityRegistry.load(path, {component.ref: component})
    assert loaded.resolve("json.parse").ref == "json.parse@1"


def test_registry_rejects_duplicate_untested_and_high_risk() -> None:
    registry, descriptor, _ = setup_registry()
    registry.register_candidate(descriptor)
    with pytest.raises(ValueError, match="already"):
        registry.register_candidate(descriptor)
    untested = CapabilityDescriptor("other", "1", "json.parse@1", "e", ("python",), ("text",), ("object",), (), 5, "zero", "LOW", "local", {})
    registry.register_candidate(untested)
    with pytest.raises(ValueError, match="without tests"):
        registry.admit(untested.ref)
