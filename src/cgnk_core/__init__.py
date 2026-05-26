"""CovenantGraph Nexus Kernel core package."""

from .bundle_validator import (
    ContractIndex,
    ReferenceCompiler,
    load_json,
    validate_bundle,
    validate_schemas,
)
from .compiler import compile_flow
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
    "compile_flow",
    "is_valid_ref",
    "load_json",
    "parse_ref",
    "ref_of",
    "validate_bundle",
    "validate_schemas",
]
