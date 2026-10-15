import pytest

from cgkn.component import PortSpec


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary]


def test_valid_port_defaults_and_projection_is_immutable() -> None:
    source = ["goal"]
    port = PortSpec("request", "artifact.raw_requirement@1", projection=source)
    source.append("source")
    assert port.required is True
    assert port.multi is False
    assert port.projection == ("goal",)
    assert PortSpec.from_dict(port.as_dict()) == port


@pytest.mark.parametrize("name, artifact_type", [("", "artifact.goal@1"), ("goal", "goal")])
@pytest.mark.negative
def test_invalid_port_is_rejected(name: str, artifact_type: str) -> None:
    with pytest.raises(ValueError):
        PortSpec(name, artifact_type)


@pytest.mark.negative
def test_port_from_dict_rejects_extra_and_missing_fields() -> None:
    with pytest.raises(ValueError, match="unknown PortSpec"):
        PortSpec.from_dict({"name": "x", "artifactType": "artifact.x@1", "extra": True})
    with pytest.raises(KeyError):
        PortSpec.from_dict({"name": "x"})
