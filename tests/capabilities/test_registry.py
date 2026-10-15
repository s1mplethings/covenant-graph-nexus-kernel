from __future__ import annotations

import pytest

from cgkn.capabilities import CapabilityDescriptor, CapabilityRegistry
from cgkn.component import ComponentSpec, PortSpec
from cgkn.capabilities.registry import CapabilityLifecycle


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]


def setup_registry():
    component = ComponentSpec("json.parse", "1", (PortSpec("text", "artifact.text@1"),), (PortSpec("object", "artifact.json@1"),))
    registry = CapabilityRegistry({component.ref: component})
    descriptor = CapabilityDescriptor("json.parse", "1", component.ref, "python.stdlib.json@1", ("python",), ("text",), ("object",), (), 5, "zero", "LOW", "stdlib", {"module": "json"}, ("tests/json_parse",))
    return registry, descriptor, component


@pytest.mark.roundtrip
@pytest.mark.determinism
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
    registry.record_execution_evidence(descriptor.ref, False)
    assert descriptor.observed_usage_count == 2 and descriptor.observed_failure == 1


@pytest.mark.negative
def test_registry_rejects_duplicate_untested_and_high_risk() -> None:
    registry, descriptor, _ = setup_registry()
    registry.register_candidate(descriptor)
    with pytest.raises(ValueError, match="already"):
        registry.register_candidate(descriptor)
    untested = CapabilityDescriptor("other", "1", "json.parse@1", "e", ("python",), ("text",), ("object",), (), 5, "zero", "LOW", "local", {})
    registry.register_candidate(untested)
    with pytest.raises(ValueError, match="without tests"):
        registry.admit(untested.ref)
    high = CapabilityDescriptor("high", "1", "json.parse@1", "e", ("python",), ("text",), ("object",), (), 5, "zero", "HIGH", "local", {}, ("test",))
    registry.register_candidate(high)
    with pytest.raises(ValueError, match="external review"):
        registry.admit(high.ref)


@pytest.mark.negative
@pytest.mark.parametrize("changes", [
    {"capability_id": ""}, {"version": "latest"}, {"executor_ref": ""}, {"timeout_seconds": 0}, {"risk_level": "UNKNOWN"},
    {"observed_usage_count": 0, "observed_success": 1},
])
def test_descriptor_validation(changes) -> None:
    _, descriptor, _ = setup_registry(); values = descriptor.__dict__.copy(); values.update(changes)
    with pytest.raises(ValueError): CapabilityDescriptor(**values)


@pytest.mark.negative
def test_registry_rejects_component_port_and_lifecycle_mismatches() -> None:
    registry, descriptor, _ = setup_registry()
    wrong = CapabilityDescriptor(**{**descriptor.__dict__, "capability_id": "wrong", "input_ports": ("other",)})
    with pytest.raises(ValueError, match="ports"):
        registry.register_candidate(wrong)
    descriptor.lifecycle_status = CapabilityLifecycle.ADMITTED
    with pytest.raises(ValueError, match="begin"):
        registry.register_candidate(descriptor)


@pytest.mark.negative
@pytest.mark.fault_injection
def test_registry_corruption_duplicate_unknown_component_and_transition_fail_closed(tmp_path) -> None:
    registry, descriptor, component = setup_registry(); registry.register_candidate(descriptor)
    with pytest.raises(ValueError, match="only an admitted"):
        registry.disable(descriptor.ref)
    with pytest.raises(ValueError, match="admitted capability"):
        registry.record_execution_evidence(descriptor.ref, True)
    registry.reject(descriptor.ref)
    with pytest.raises(ValueError, match="current lifecycle"):
        registry.admit(descriptor.ref)
    with pytest.raises(KeyError): registry.resolve("missing")
    path = tmp_path / "registry.json"; path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="unreadable"):
        CapabilityRegistry.load(path, {component.ref: component})
    raw = descriptor.as_dict(); raw["lifecycle_status"] = "CANDIDATE"
    path.write_text(__import__("json").dumps({"kind": "CGKNCapabilityRegistry", "schema_version": "1.0", "capabilities": [raw, raw]}), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        CapabilityRegistry.load(path, {component.ref: component})
    raw["component_ref"] = "missing@1"
    path.write_text(__import__("json").dumps({"kind": "CGKNCapabilityRegistry", "schema_version": "1.0", "capabilities": [raw]}), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown"):
        CapabilityRegistry.load(path, {component.ref: component})


@pytest.mark.fault_injection
@pytest.mark.recovery
def test_registry_atomic_save_failure_preserves_previous_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, descriptor, _ = setup_registry(); registry.register_candidate(descriptor)
    path = tmp_path / "registry.json"; path.write_text("previous\n", encoding="utf-8")
    monkeypatch.setattr("cgkn.capabilities.registry.os.replace", lambda *_args: (_ for _ in ()).throw(OSError("replace")))
    with pytest.raises(OSError, match="replace"): registry.save(path)
    assert path.read_text(encoding="utf-8") == "previous\n"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.negative
def test_registry_rejects_unknown_component_and_invalid_transitions() -> None:
    registry, descriptor, _ = setup_registry()
    descriptor.component_ref = "missing@1"
    with pytest.raises(ValueError, match="unknown ComponentSpec"):
        registry.register_candidate(descriptor)
    registry, descriptor, _ = setup_registry(); registry.register_candidate(descriptor)
    with pytest.raises(ValueError, match="current lifecycle"):
        registry.admit(descriptor.ref); registry.reject(descriptor.ref)
    registry, descriptor, _ = setup_registry(); registry.register_candidate(descriptor); registry.admit(descriptor.ref)
    registry.disable(descriptor.ref)
    assert descriptor.lifecycle_status is CapabilityLifecycle.DISABLED
    with pytest.raises(KeyError):
        registry.record_execution_evidence("missing@1", True)


@pytest.mark.negative
@pytest.mark.fault_injection
@pytest.mark.parametrize("mutation,match", [
    (lambda document: document.update(schema_version="9"), "unsupported"),
    (lambda document: document["capabilities"].append("bad"), "invalid persisted"),
    (lambda document: document["capabilities"][0].update(input_ports=["wrong"]), "ports"),
])
def test_registry_load_rejects_invalid_persisted_shapes(tmp_path, mutation, match) -> None:
    import json
    registry, descriptor, component = setup_registry(); registry.register_candidate(descriptor)
    document = {"kind": "CGKNCapabilityRegistry", "schema_version": "1.0", "capabilities": [descriptor.as_dict()]}
    mutation(document)
    path = tmp_path / "registry.json"; path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        CapabilityRegistry.load(path, {component.ref: component})
