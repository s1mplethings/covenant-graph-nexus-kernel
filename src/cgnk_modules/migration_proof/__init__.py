"""Clean-room implementation for module.migration.proof@1."""

from .contracts import MODULE_REF, OUTPUT_ARTIFACT_REF, check_contract_conformance
from .proof import build_migration_proof

__all__ = ["MODULE_REF", "OUTPUT_ARTIFACT_REF", "build_migration_proof", "check_contract_conformance"]
