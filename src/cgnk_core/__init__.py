"""CovenantGraph Nexus Kernel core package."""

from .bundle_validator import (
    ContractIndex,
    ReferenceCompiler,
    load_json,
    validate_bundle,
    validate_schemas,
)
from .compiler import compile_flow
from .contract_pack import build_agent_contract_pack
from .diff import diff_compile_results
from .diagnostics import Diagnostic
from .graph_edit import apply_graph_edit_proposal
from .refs import is_valid_ref, parse_ref, ref_of
from .registry import ContractRegistry
from .schema_loader import SchemaLoader
from .semantic_validator import SemanticValidator

__all__ = [
    "ContractIndex",
    "ContractRegistry",
    "Diagnostic",
    "ReferenceCompiler",
    "SchemaLoader",
    "SemanticValidator",
    "apply_graph_edit_proposal",
    "build_agent_contract_pack",
    "compile_flow",
    "diff_compile_results",
    "is_valid_ref",
    "load_json",
    "parse_ref",
    "ref_of",
    "validate_bundle",
    "validate_schemas",
]
