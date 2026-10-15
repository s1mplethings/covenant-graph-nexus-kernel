import pytest

from cgkn.component import ComponentSpec, PortSpec


def test_component_spec_has_stable_ref_ports_effects_and_metadata() -> None:
    input_port = PortSpec("source", "artifact.project_source@1")
    output_port = PortSpec("snapshot", "artifact.project_snapshot@1")
    spec = ComponentSpec("module.snapshot", "1", (input_port,), (output_port,), {"fs_read": ["**"]}, "policy.safe@1", {"owner": "kernel"})
    assert spec.ref == "module.snapshot@1"
    assert spec.input_port("source") is input_port
    assert spec.output_port("snapshot") is output_port
    assert spec.effects["fs_read"] == ("**",)
    assert spec.policy_ref == "policy.safe@1" and spec.metadata["owner"] == "kernel"
    assert ComponentSpec.from_dict(spec.as_dict()) == spec


@pytest.mark.parametrize("component_id, version", [("", "1"), ("module.x", "")])
def test_empty_identity_is_rejected(component_id: str, version: str) -> None:
    with pytest.raises(ValueError):
        ComponentSpec(component_id, version)


@pytest.mark.parametrize("side", ["input", "output"])
def test_duplicate_port_names_are_rejected(side: str) -> None:
    ports = (PortSpec("same", "artifact.goal@1"), PortSpec("same", "artifact.goal@1"))
    with pytest.raises(ValueError):
        ComponentSpec("module.x", "1", ports if side == "input" else (), ports if side == "output" else ())


def test_cross_boundary_port_collision_is_rejected() -> None:
    port = PortSpec("same", "artifact.goal@1")
    with pytest.raises(ValueError, match="must not collide"):
        ComponentSpec("module.x", "1", (port,), (port,))


def test_invalid_version_and_nested_mutation_are_rejected() -> None:
    with pytest.raises(ValueError, match="numeric dotted"):
        ComponentSpec("module.x", "latest")
    source = {"nested": {"allowed": ["read"]}}
    spec = ComponentSpec("module.x", "1.2.0", effects=source)
    source["nested"]["allowed"].append("write")
    assert spec.effects["nested"]["allowed"] == ("read",)
    with pytest.raises(TypeError):
        spec.effects["nested"]["new"] = True
