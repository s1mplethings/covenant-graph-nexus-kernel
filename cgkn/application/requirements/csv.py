from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cgkn.application.software_project.catalog import get_case

from .compiler import NormalizedRequirements, RequirementCompiler
from .obligation import ObligationSet, RequirementSource, RequirementSourceType
from .policy import DependencyDomainPolicy, DependencyPolicy, NetworkPolicy
from .receipt import ObligationPreflightReceipt
from .traceability import TestBinding, TraceabilityGraph, build_traceability, validate_traceability
from .validator import ObligationCompletenessValidator


CSV_DEPENDENCY_POLICY = DependencyPolicy(
    "POLICY-CSV-DEPS-001",
    runtime=DependencyDomainPolicy(stdlib_only=True),
    development=DependencyDomainPolicy(),
    test=DependencyDomainPolicy(allowed_packages=("pytest",)),
    tooling=DependencyDomainPolicy(allowed_packages=("pytest",)),
    network=NetworkPolicy("FORBIDDEN"),
)


@dataclass(frozen=True)
class CSVRequirementCompilation:
    requirements: NormalizedRequirements
    obligations: ObligationSet
    traceability: TraceabilityGraph
    preflight: ObligationPreflightReceipt

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirements": self.requirements.as_dict(),
            "obligations": self.obligations.as_dict(),
            "traceability": self.traceability.as_dict(),
            "obligation_preflight": self.preflight.as_dict(),
        }


@dataclass(frozen=True)
class CSVPublicContractCompilation:
    """Public-only canonical inputs for deterministic downstream projections.

    Unlike ``CSVRequirementCompilation`` this object never loads the hidden
    acceptance manifest.  It is therefore safe to project into Provider
    context after further minimization.
    """

    requirements: NormalizedRequirements
    obligations: ObligationSet

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirements": self.requirements.as_dict(),
            "obligations": self.obligations.as_dict(),
        }


def _sources() -> tuple[RequirementSource, ...]:
    case = get_case("cli_csv_cleaner")
    sources = [RequirementSource("REQ-CSV-GOAL", case.public_goal, RequirementSourceType.USER_EXPLICIT, 10)]
    sources.extend(
        RequirementSource(f"REQ-CSV-ACCEPT-{index:02d}", text, RequirementSourceType.USER_EXPLICIT, 20 + index)
        for index, text in enumerate(case.public_acceptance, 1)
    )
    sources.extend((
        RequirementSource("REQ-CSV-POLICY-RUNTIME", "Runtime code uses only the Python standard library.", RequirementSourceType.PLATFORM_POLICY, 50),
        RequirementSource("REQ-CSV-POLICY-TEST", "Generated project tests may use pytest.", RequirementSourceType.PLATFORM_POLICY, 51),
        RequirementSource("REQ-CSV-POLICY-NETWORK", "The project makes no outbound network requests.", RequirementSourceType.PLATFORM_POLICY, 52),
    ))
    return tuple(sources)


def _spec(identifier: str, kind: str, subject: str, refs: tuple[str, ...], expected: dict[str, Any], *,
          preconditions: dict[str, Any] | None = None, forbidden: dict[str, Any] | None = None,
          operation: dict[str, Any] | None = None, verification: tuple[str, ...] = ("public_test", "hidden_acceptance"),
          dependency_policy: DependencyPolicy | None = None) -> dict[str, Any]:
    return {
        "obligation_id": identifier,
        "kind": kind,
        "subject": subject,
        "source_requirement_refs": refs,
        "preconditions": preconditions or {},
        "operation": operation or {},
        "expected": expected,
        "forbidden": forbidden or {},
        "dependency_policy": dependency_policy.as_dict() if dependency_policy else None,
        "verification_method": verification,
        "scope": ("cli_csv_cleaner",),
        "provenance": {"compiler": "csv_requirement_compiler@1", "authority": "public_contract"},
    }


def _specs(require_malformed_rejection: bool) -> tuple[dict[str, Any], ...]:
    goal = ("REQ-CSV-GOAL",)
    a1, a2, a3, a4, a5 = (f"REQ-CSV-ACCEPT-{index:02d}" for index in range(1, 6))
    specs = [
        _spec("OBL-CSV-INPUT-OUTPUT", "RUNTIME", "read an input CSV and write a distinct output CSV", goal + (a3,), {"input_format": "CSV", "output_format": "CSV", "output_created": True}),
        _spec("OBL-CSV-HEADER-PRESERVATION", "BEHAVIOR", "preserve CSV headers", goal + (a3,), {"header": "unchanged"}),
        _spec("OBL-CSV-DEDUP-WHOLE-ROW", "BEHAVIOR", "deduplicate identical data rows", goal + (a1,), {"duplicates": "first occurrence retained"}),
        _spec("OBL-CSV-DEDUP-COLUMN", "BEHAVIOR", "deduplicate data rows by a selected column", goal + (a1,), {"duplicates": "first selected-column occurrence retained"}),
        _spec("OBL-CSV-STABLE-ORDER", "BEHAVIOR", "preserve relative order while deduplicating", goal + (a1,), {"row_order": "stable"}),
        _spec("OBL-CSV-FILL-EMPTY", "BEHAVIOR", "fill every empty field when --fill is supplied", goal + (a2,), {"all_empty_fields": "fill_value"}),
        _spec("OBL-CSV-PREVIEW", "INTERFACE", "print the first N cleaned data rows as CSV", goal + (a2,), {"stdout": "at most N cleaned data rows; header excluded"}),
        _spec("OBL-CSV-PREVIEW-WRITES-OUTPUT", "STATE_TRANSITION", "preview does not suppress output-file creation", goal + (a2,), {"output_created": True, "preview_emitted": True}),
        _spec("OBL-CSV-CLI-HELP", "INTERFACE", "provide the documented module CLI help", goal + (a3,), {"command": "python -m csv_cleaner --help", "exit_code": 0}),
        _spec("OBL-CSV-ERR-UNKNOWN-COLUMN", "ERROR_SEMANTICS", "reject an unknown dedupe column", goal + (a3,), {"exit_code": "nonzero", "error_text": "nonempty"}, preconditions={"dedupe_column_missing_from_header": True}, forbidden={"successful_output_commit": True}),
        _spec("OBL-CSV-ERR-NONZERO", "ERROR_SEMANTICS", "report invalid public CLI input as a clear non-zero error", goal + (a3,), {"exit_code": "nonzero", "error_text": "nonempty"}, preconditions={"public_cli_input_invalid": True}),
        _spec("OBL-CSV-README", "DOCUMENTATION", "include README usage for the public CLI", goal + (a4,), {"documents_entrypoint": True, "documents_options": True}, verification=("static_inspection",)),
        _spec("OBL-CSV-PUBLIC-TESTS", "TESTABILITY", "include runnable pytest public tests", goal + (a4,), {"pytest_exit_code": 0}, verification=("pytest",)),
        _spec("OBL-CSV-RUNTIME-STDLIB", "DEPENDENCY_POLICY", "runtime dependencies are standard-library only", ("REQ-CSV-POLICY-RUNTIME", a5), {"runtime_stdlib_only": True}, verification=("dependency_scan",), dependency_policy=CSV_DEPENDENCY_POLICY),
        _spec("OBL-CSV-TEST-PYTEST", "DEPENDENCY_POLICY", "pytest is permitted only for test and tooling code", ("REQ-CSV-POLICY-TEST", a4, a5), {"test_pytest_allowed": True, "runtime_pytest_allowed": False}, verification=("dependency_scan",), dependency_policy=CSV_DEPENDENCY_POLICY),
        _spec("OBL-CSV-NETWORK-OFFLINE", "RESOURCE_BOUNDARY", "forbid outbound network access", ("REQ-CSV-POLICY-NETWORK", a5), {"network_outbound": "FORBIDDEN"}, verification=("network_guard",), dependency_policy=CSV_DEPENDENCY_POLICY),
    ]
    if require_malformed_rejection:
        specs.append(_spec(
            "OBL-CSV-ERR-MALFORMED", "ERROR_SEMANTICS", "reject malformed CSV syntax", ("REQ-CSV-GOAL",),
            {"exit_code": "nonzero", "error_text": "nonempty"}, preconditions={"csv_syntax_malformed": True},
            forbidden={"successful_output_commit": True},
        ))
    return tuple(specs)


def _load_hidden_bindings(path: Path) -> tuple[TestBinding, ...]:
    document = json.loads(path.read_text(encoding="utf-8"))
    return tuple(TestBinding(str(item["test_id"]), tuple(item["obligation_ids"]), hidden=True) for item in document["tests"])


def compile_csv_public_contract(*, require_malformed_rejection: bool = False) -> CSVPublicContractCompilation:
    """Compile only public requirement sources and their canonical obligations."""

    compiler = RequirementCompiler()
    sources = _sources()
    public_refs = tuple(item.source_id for item in sources if item.source_id.startswith("REQ-CSV-ACCEPT-"))
    requirements = compiler.normalize(sources, public_refs)
    obligations = compiler.compile(requirements, _specs(require_malformed_rejection))
    return CSVPublicContractCompilation(requirements, obligations)


def compile_csv_cleaner(
    *,
    require_malformed_rejection: bool = False,
    hidden_manifest: str | Path | None = None,
) -> CSVRequirementCompilation:
    public = compile_csv_public_contract(require_malformed_rejection=require_malformed_rejection)
    requirements = public.requirements
    obligations = public.obligations
    public_bindings = tuple(
        TestBinding(f"TEST-PUBLIC-{item.obligation_id.removeprefix('OBL-')}", (item.obligation_id,))
        for item in obligations.obligations
        if "public_test" in item.verification_method
    )
    manifest = Path(hidden_manifest) if hidden_manifest else Path(__file__).parents[3] / "benchmarks" / "real_project_generation" / "acceptance" / "cli_csv_cleaner.obligations.json"
    hidden_bindings = _load_hidden_bindings(manifest)
    graph = build_traceability(requirements, obligations, tests=public_bindings + hidden_bindings)
    validation = ObligationCompletenessValidator().validate(requirements, obligations)
    traceability = validate_traceability(requirements, obligations, graph)
    ambiguous = () if require_malformed_rejection else ("malformed_csv=UNSPECIFIED",)
    hidden_coverage = {
        "coverage": traceability.hidden_acceptance_coverage,
        "status": traceability.status,
        "test_count": len(hidden_bindings),
        "bound_obligation_ids": sorted({identifier for binding in hidden_bindings for identifier in binding.obligation_ids}),
    }
    preflight = ObligationPreflightReceipt.build(
        requirements, obligations, validation, traceability,
        ambiguous_behaviors=ambiguous, hidden_coverage=hidden_coverage,
    )
    return CSVRequirementCompilation(requirements, obligations, graph, preflight)
