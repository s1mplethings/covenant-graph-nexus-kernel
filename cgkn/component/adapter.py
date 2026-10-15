from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .ports import PortSpec
from .protocol import ComponentInputs, ExecutionContext
from .result import ComponentResult
from .spec import ComponentSpec, _freeze, _thaw


ModuleExecutor = Callable[[dict[str, Any], ComponentInputs, ExecutionContext], ComponentResult]


@dataclass(frozen=True)
class ModuleComponentAdapter:
    """Compatibility boundary from a canonical module contract to Component."""

    module_contract: Mapping[str, Any]
    executor: ModuleExecutor | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "module_contract", _freeze(self.module_contract))

    @property
    def spec(self) -> ComponentSpec:
        module = self.module_contract
        return ComponentSpec(
            component_id=str(module["id"]),
            version=str(module["version"]),
            input_ports=self._ports("input"),
            output_ports=self._ports("output"),
            effects=module.get("effects", {}),
            policy_ref=module.get("policy_ref"),
            metadata={
                **module.get("metadata", {}),
                "context": module.get("context", {}),
                "implementation": module.get("implementation", {}),
            },
        )

    def execute(self, context: ExecutionContext, inputs: ComponentInputs) -> ComponentResult:
        if self.executor is None:
            raise RuntimeError(f"component has no runtime executor: {self.spec.ref}")
        return self.executor(_thaw(self.module_contract), inputs, context)

    def _ports(self, side: str) -> tuple[PortSpec, ...]:
        return tuple(
            PortSpec(
                name=name,
                artifact_type=str(value["artifact_type"]),
                required=bool(value.get("required", side == "output")),
                multi=bool(value.get("multi", False)),
                projection=tuple(value.get("projection", ())),
            )
            for name, value in self.module_contract.get("ports", {}).get(side, {}).items()
        )
