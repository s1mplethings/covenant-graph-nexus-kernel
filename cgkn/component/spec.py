from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Any, Mapping

from .ports import PortSpec


_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class ComponentSpec:
    """Stable component definition. Runtime state belongs to ComponentExecution."""

    component_id: str
    version: str
    input_ports: tuple[PortSpec, ...] = ()
    output_ports: tuple[PortSpec, ...] = ()
    effects: Mapping[str, Any] = field(default_factory=dict)
    policy_ref: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.component_id.strip():
            raise ValueError("component_id is required")
        if not _VERSION.fullmatch(self.version):
            raise ValueError("component version must be a numeric dotted version")
        object.__setattr__(self, "input_ports", tuple(self.input_ports))
        object.__setattr__(self, "output_ports", tuple(self.output_ports))
        self._reject_duplicate_names(self.input_ports, "input")
        self._reject_duplicate_names(self.output_ports, "output")
        if {port.name for port in self.input_ports} & {port.name for port in self.output_ports}:
            raise ValueError("input and output port names must not collide")
        object.__setattr__(self, "effects", _freeze(self.effects))
        object.__setattr__(self, "metadata", _freeze(self.metadata))

    @property
    def ref(self) -> str:
        return f"{self.component_id}@{self.version}"

    def input_port(self, name: str) -> PortSpec:
        return self._port(self.input_ports, name, "input")

    def output_port(self, name: str) -> PortSpec:
        return self._port(self.output_ports, name, "output")

    def as_dict(self) -> dict[str, Any]:
        return {
            "componentId": self.component_id,
            "version": self.version,
            "inputPorts": [port.as_dict() for port in self.input_ports],
            "outputPorts": [port.as_dict() for port in self.output_ports],
            "effects": _thaw(self.effects),
            "policyRef": self.policy_ref,
            "metadata": _thaw(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComponentSpec":
        allowed = {"componentId", "version", "inputPorts", "outputPorts", "effects", "policyRef", "metadata"}
        if set(value) - allowed:
            raise ValueError("unknown ComponentSpec fields")
        return cls(
            component_id=str(value["componentId"]),
            version=str(value["version"]),
            input_ports=tuple(PortSpec.from_dict(item) for item in value.get("inputPorts", ())),
            output_ports=tuple(PortSpec.from_dict(item) for item in value.get("outputPorts", ())),
            effects=dict(value.get("effects", {})),
            policy_ref=value.get("policyRef"),
            metadata=dict(value.get("metadata", {})),
        )

    @staticmethod
    def _reject_duplicate_names(ports: tuple[PortSpec, ...], side: str) -> None:
        names = [port.name for port in ports]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate {side} port name")

    @staticmethod
    def _port(ports: tuple[PortSpec, ...], name: str, side: str) -> PortSpec:
        try:
            return next(port for port in ports if port.name == name)
        except StopIteration as exc:
            raise KeyError(f"{side} port does not exist: {name}") from exc


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value
