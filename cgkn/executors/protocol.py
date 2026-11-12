from __future__ import annotations

from typing import Protocol, runtime_checkable

from cgkn.execution import BlockExecutionRequest, BlockExecutionResult
from cgkn.execution.contracts import ExecutorDescriptor


@runtime_checkable
class Executor(Protocol):
    descriptor: ExecutorDescriptor

    def execute(self, request: BlockExecutionRequest) -> BlockExecutionResult: ...
