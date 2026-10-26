from __future__ import annotations

from .protocol import Executor


class ExecutorResolutionError(LookupError):
    pass


class ExecutorRegistry:
    def __init__(self) -> None:
        self._executors: dict[str, Executor] = {}

    def register(self, executor: Executor) -> None:
        ref = executor.descriptor.executor_ref
        if ref in self._executors:
            raise ValueError(f"duplicate executor authority: {ref}")
        self._executors[ref] = executor

    def unregister(self, executor_ref: str) -> None:
        if executor_ref not in self._executors:
            raise ExecutorResolutionError(f"executor not found: {executor_ref}")
        del self._executors[executor_ref]

    def resolve(self, executor_ref: str, component_ref: str) -> Executor:
        executor = self._executors.get(executor_ref)
        if executor is None:
            raise ExecutorResolutionError(f"executor not found: {executor_ref}")
        if not executor.descriptor.enabled:
            raise ExecutorResolutionError(f"executor disabled: {executor_ref}")
        if not executor.descriptor.supports(component_ref):
            raise ExecutorResolutionError(f"executor {executor_ref} does not support {component_ref}")
        return executor

    def list(self) -> tuple[Executor, ...]:
        return tuple(self._executors[key] for key in sorted(self._executors))
