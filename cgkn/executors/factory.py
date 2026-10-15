from __future__ import annotations

from collections.abc import Callable

from cgkn.capabilities import CapabilityDescriptor

from .protocol import Executor


class ExecutorFactoryRegistry:
    """Map an admitted implementation identity to a bounded executor factory."""

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[CapabilityDescriptor], Executor]] = {}

    def register(self, implementation_identity: str, factory: Callable[[CapabilityDescriptor], Executor]) -> None:
        identity = implementation_identity.strip()
        if not identity or identity in self._factories:
            raise ValueError("executor factory identity must be unique and non-empty")
        self._factories[identity] = factory

    def create(self, descriptor: CapabilityDescriptor) -> Executor:
        identity = str(descriptor.provenance.get("implementation_identity") or descriptor.provenance.get("callable") or "").strip()
        if identity not in self._factories:
            raise LookupError(f"executor factory unavailable for implementation: {identity or '<missing>'}")
        executor = self._factories[identity](descriptor)
        if executor.descriptor.executor_ref != descriptor.executor_ref:
            raise ValueError("executor factory returned a mismatched executor_ref")
        return executor
