"""Clean-room implementation for module.project.build_graph@1."""

from .contracts import INPUT_ARTIFACT_REF, MODULE_REF, OUTPUT_ARTIFACT_REF, check_contract_conformance
from .graph import build_project_graph

__all__ = [
    "INPUT_ARTIFACT_REF",
    "MODULE_REF",
    "OUTPUT_ARTIFACT_REF",
    "build_project_graph",
    "check_contract_conformance",
]
