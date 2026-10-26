from cgkn.capabilities import CapabilityDescriptor, CapabilityLifecycle, CapabilityRegistry
from cgkn.component import ComponentSpec


def descriptor(version: str) -> CapabilityDescriptor:
    return CapabilityDescriptor("demo", version, "demo@1", "demo.exec@1", ("demo",), (), (), (), 5, "LOW", "LOW", "test", {"implementation_identity": "demo"}, ("test",), CapabilityLifecycle.CANDIDATE)


def test_registry_resolves_numeric_semantic_order() -> None:
    registry = CapabilityRegistry({"demo@1": ComponentSpec("demo", "1", (), ())})
    for version in ("1.9", "2.0", "1.10"):
        item = descriptor(version)
        registry.register_candidate(item)
        registry.admit(item.ref)
    assert registry.resolve("demo").version == "2.0"


def test_registry_rejects_non_numeric_versions() -> None:
    registry = CapabilityRegistry({"demo@1": ComponentSpec("demo", "1", (), ())})
    try:
        registry.register_candidate(descriptor("latest"))
    except ValueError as exc:
        assert "unsupported capability version" in str(exc)
    else:
        raise AssertionError("invalid version was accepted")
