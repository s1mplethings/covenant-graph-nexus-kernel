from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult


@dataclass(frozen=True)
class ExecutorDescriptor:
    executor_ref: str
    kind: str
    supported_refs: tuple[str, ...]
    effects: tuple[str, ...] = ()
    supports_timeout: bool = True
    supports_cost_reporting: bool = False
    locality: str = "local"
    enabled: bool = True

    def supports(self, component_ref: str) -> bool:
        return "*" in self.supported_refs or component_ref in self.supported_refs


@runtime_checkable
class Executor(Protocol):
    descriptor: ExecutorDescriptor

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult: ...
