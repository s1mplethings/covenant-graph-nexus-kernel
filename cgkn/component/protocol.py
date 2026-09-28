from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from cgkn.artifacts.models import ArtifactRef

from .result import ComponentResult
from .spec import ComponentSpec


ComponentInputs = Mapping[str, ArtifactRef]


@dataclass(frozen=True)
class ExecutionContext:
    run_id: str
    node: Mapping[str, Any]
    context_pack: Mapping[str, Any]


@runtime_checkable
class Component(Protocol):
    @property
    def spec(self) -> ComponentSpec: ...

    def execute(self, context: ExecutionContext, inputs: ComponentInputs) -> ComponentResult: ...
