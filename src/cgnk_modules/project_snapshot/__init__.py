"""Clean-room implementation for module.project.snapshot@1."""

from .contracts import MODULE_REF, OUTPUT_ARTIFACT_REF, check_contract_conformance
from .snapshot import collect_project_snapshot

__all__ = [
    "MODULE_REF",
    "OUTPUT_ARTIFACT_REF",
    "check_contract_conformance",
    "collect_project_snapshot",
]
