from __future__ import annotations

import json
import pathlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from cgkn.component import ComponentSpec


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CapabilityLifecycle(str, Enum):
    CANDIDATE = "CANDIDATE"
    VERIFIED = "VERIFIED"
    ADMITTED = "ADMITTED"
    DISABLED = "DISABLED"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"


@dataclass
class CapabilityDescriptor:
    capability_id: str
    version: str
    component_ref: str
    executor_ref: str
    allowed_executor_kinds: tuple[str, ...]
    input_ports: tuple[str, ...]
    output_ports: tuple[str, ...]
    declared_effects: tuple[str, ...]
    timeout_seconds: float
    cost_hint: str
    risk_level: str
    source: str
    provenance: Mapping[str, Any]
    test_refs: tuple[str, ...] = ()
    lifecycle_status: CapabilityLifecycle = CapabilityLifecycle.CANDIDATE
    observed_usage_count: int = 0
    observed_success: int = 0
    observed_failure: int = 0
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)

    @property
    def ref(self) -> str:
        return f"{self.capability_id}@{self.version}"

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["lifecycle_status"] = self.lifecycle_status.value
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapabilityDescriptor":
        data = dict(value)
        data["lifecycle_status"] = CapabilityLifecycle(data["lifecycle_status"])
        for key in ("allowed_executor_kinds", "input_ports", "output_ports", "declared_effects", "test_refs"):
            data[key] = tuple(data.get(key, ()))
        return cls(**data)


class CapabilityRegistry:
    def __init__(self, components: Mapping[str, ComponentSpec]):
        self.components = dict(components)
        self._items: dict[str, CapabilityDescriptor] = {}

    def register_candidate(self, descriptor: CapabilityDescriptor) -> None:
        if descriptor.ref in self._items:
            raise ValueError(f"capability version already registered: {descriptor.ref}")
        component = self.components.get(descriptor.component_ref)
        if component is None:
            raise ValueError("descriptor references unknown ComponentSpec")
        if tuple(port.name for port in component.input_ports) != descriptor.input_ports or tuple(port.name for port in component.output_ports) != descriptor.output_ports:
            raise ValueError("descriptor ports do not match ComponentSpec")
        if descriptor.lifecycle_status is not CapabilityLifecycle.CANDIDATE:
            raise ValueError("new capability must begin as CANDIDATE")
        self._items[descriptor.ref] = descriptor

    def admit(self, ref: str) -> None:
        item = self._require(ref)
        if not item.test_refs:
            raise ValueError("candidate without tests cannot be admitted")
        if item.risk_level.upper() == "HIGH":
            raise ValueError("high-risk capability requires external review")
        item.lifecycle_status = CapabilityLifecycle.ADMITTED
        item.updated_at = now()

    def reject(self, ref: str) -> None:
        self._transition(ref, CapabilityLifecycle.REJECTED)

    def disable(self, ref: str) -> None:
        self._transition(ref, CapabilityLifecycle.DISABLED)

    def resolve(self, capability_id: str, version: str | None = None) -> CapabilityDescriptor:
        candidates = [item for item in self._items.values() if item.capability_id == capability_id and item.lifecycle_status is CapabilityLifecycle.ADMITTED and (version is None or item.version == version)]
        if not candidates:
            raise KeyError(f"admitted capability not found: {capability_id}")
        return sorted(candidates, key=lambda item: item.version)[-1]

    def query(self, *, input_port: str | None = None, output_port: str | None = None, effect: str | None = None) -> tuple[CapabilityDescriptor, ...]:
        return tuple(item for item in sorted(self._items.values(), key=lambda value: value.ref) if (input_port is None or input_port in item.input_ports) and (output_port is None or output_port in item.output_ports) and (effect is None or effect in item.declared_effects))

    def record_execution_evidence(self, ref: str, succeeded: bool) -> None:
        item = self._require(ref)
        item.observed_usage_count += 1
        if succeeded:
            item.observed_success += 1
        else:
            item.observed_failure += 1
        item.updated_at = now()

    def save(self, path: pathlib.Path | str) -> None:
        target = pathlib.Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"kind": "CGKNCapabilityRegistry", "schema_version": "1.0", "capabilities": [item.as_dict() for item in self.query()]}, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: pathlib.Path | str, components: Mapping[str, ComponentSpec]) -> "CapabilityRegistry":
        value = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        if value.get("kind") != "CGKNCapabilityRegistry" or value.get("schema_version") != "1.0":
            raise ValueError("unsupported capability registry")
        registry = cls(components)
        for raw in value.get("capabilities", []):
            item = CapabilityDescriptor.from_dict(raw)
            if item.ref in registry._items:
                raise ValueError("duplicate capability in persisted registry")
            if item.component_ref not in registry.components:
                raise ValueError("persisted capability references unknown ComponentSpec")
            registry._items[item.ref] = item
        return registry

    def _require(self, ref: str) -> CapabilityDescriptor:
        if ref not in self._items:
            raise KeyError(ref)
        return self._items[ref]

    def _transition(self, ref: str, status: CapabilityLifecycle) -> None:
        item = self._require(ref)
        item.lifecycle_status = status
        item.updated_at = now()
