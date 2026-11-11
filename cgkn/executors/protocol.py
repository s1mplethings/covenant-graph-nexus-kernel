from __future__ import annotations

from dataclasses import dataclass
import math
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
    default_timeout_seconds: float = 30.0

    def __post_init__(self):
        value = self.default_timeout_seconds
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("executor default timeout must be finite and positive")

    def supports(self, component_ref: str) -> bool:
        return "*" in self.supported_refs or component_ref in self.supported_refs


@runtime_checkable
class Executor(Protocol):
    descriptor: ExecutorDescriptor

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult: ...
