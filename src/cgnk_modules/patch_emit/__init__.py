"""Clean-room implementation for module.patch.emit@1."""

from .contracts import MODULE_REF, OUTPUT_ARTIFACT_REF, check_contract_conformance
from .emit import emit_patch_manifest

__all__ = ["MODULE_REF", "OUTPUT_ARTIFACT_REF", "check_contract_conformance", "emit_patch_manifest"]
