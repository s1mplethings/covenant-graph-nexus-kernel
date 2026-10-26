from __future__ import annotations

from dataclasses import dataclass

from .contracts import ExecutableInterfaceContract, ExecutableInterfaceContractSet


@dataclass(frozen=True)
class InterfaceContractRegistry:
    """Read-only lookup convenience; it does not create or override authority."""

    contract_set: ExecutableInterfaceContractSet

    def get(self, contract_id: str) -> ExecutableInterfaceContract:
        return self.contract_set.by_id(contract_id)

    def select(self, contract_ids: tuple[str, ...]) -> tuple[ExecutableInterfaceContract, ...]:
        return tuple(self.get(identifier) for identifier in contract_ids)
