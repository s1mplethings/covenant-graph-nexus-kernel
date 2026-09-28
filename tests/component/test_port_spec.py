import pytest

from cgkn.component import PortSpec


def test_valid_port_defaults_and_projection_is_immutable() -> None:
    source = ["goal"]
    port = PortSpec("request", "artifact.raw_requirement@1", projection=source)
    source.append("source")
    assert port.required is True
    assert port.multi is False
    assert port.projection == ("goal",)


@pytest.mark.parametrize("name, artifact_type", [("", "artifact.goal@1"), ("goal", "goal")])
def test_invalid_port_is_rejected(name: str, artifact_type: str) -> None:
    with pytest.raises(ValueError):
        PortSpec(name, artifact_type)
