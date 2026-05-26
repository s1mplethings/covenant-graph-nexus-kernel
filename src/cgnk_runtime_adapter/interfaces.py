from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class RuntimeRequest:
    compiled_contract_bundle: dict[str, Any]
    inputs: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceBundle:
    artifacts: dict[str, Any] = field(default_factory=dict)
    file_hashes: dict[str, str] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProviderCallLedger:
    calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    diagnostics: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RuntimeResult:
    ok: bool
    outputs: dict[str, Any]
    evidence: EvidenceBundle
    provider_ledger: ProviderCallLedger
    validation: ValidationResult


class RuntimeAdapter(Protocol):
    def run(self, request: RuntimeRequest) -> RuntimeResult:
        """Execute a downstream runtime from a compiled bundle.

        CGNK core does not implement this method and does not generate projects.
        """
