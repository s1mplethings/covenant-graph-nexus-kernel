"""Clean-room implementation for module.trace.summary@1."""

from .contracts import MODULE_REF, OUTPUT_ARTIFACT_REF, check_contract_conformance
from .summary import summarize_trace_events

__all__ = [
    "MODULE_REF",
    "OUTPUT_ARTIFACT_REF",
    "check_contract_conformance",
    "summarize_trace_events",
]
