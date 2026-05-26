"""Contract-only runtime adapter boundary for future CGNK runtimes."""

from .contracts import validate_runtime_adapter_contract
from .interfaces import (
    EvidenceBundle,
    ProviderCallLedger,
    RuntimeAdapter,
    RuntimeRequest,
    RuntimeResult,
    ValidationResult,
)

__all__ = [
    "EvidenceBundle",
    "ProviderCallLedger",
    "RuntimeAdapter",
    "RuntimeRequest",
    "RuntimeResult",
    "ValidationResult",
    "validate_runtime_adapter_contract",
]
