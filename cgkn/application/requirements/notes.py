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


NOTES_DEPENDENCY_POLICY = DependencyPolicy(
    "POLICY-NOTES-DEPS-001",
    runtime=DependencyDomainPolicy(stdlib_only=True), development=DependencyDomainPolicy(),
    test=DependencyDomainPolicy(allowed_packages=("pytest",)), tooling=DependencyDomainPolicy(allowed_packages=("pytest",)),
    network=NetworkPolicy("FORBIDDEN"),
)


@dataclass(frozen=True)
class NotesRequirementCompilation:
    requirements: NormalizedRequirements
    obligations: ObligationSet
    traceability: TraceabilityGraph
    preflight: ObligationPreflightReceipt

    def as_dict(self) -> dict[str, Any]:
        return {"requirements": self.requirements.as_dict(), "obligations": self.obligations.as_dict(),
                "traceability": self.traceability.as_dict(), "obligation_preflight": self.preflight.as_dict()}


def _sources() -> tuple[RequirementSource, ...]:
    case = get_case("local_json_notes")
    result = [RequirementSource("REQ-NOTES-GOAL", case.public_goal, RequirementSourceType.USER_EXPLICIT, 10)]
    result.extend(RequirementSource(f"REQ-NOTES-ACCEPT-{i:02d}", text, RequirementSourceType.USER_EXPLICIT, 20 + i)
                  for i, text in enumerate(case.public_acceptance, 1))
    result.extend((
        RequirementSource("REQ-NOTES-POLICY-RUNTIME", "Runtime code uses only the Python standard library.", RequirementSourceType.PLATFORM_POLICY, 50),
        RequirementSource("REQ-NOTES-POLICY-TEST", "Generated project tests may use pytest.", RequirementSourceType.PLATFORM_POLICY, 51),
        RequirementSource("REQ-NOTES-POLICY-NETWORK", "The project makes no outbound network requests.", RequirementSourceType.PLATFORM_POLICY, 52),
    ))
    return tuple(result)


def _spec(identifier: str, kind: str, subject: str, expected: dict[str, Any], *, refs: tuple[str, ...] = ("REQ-NOTES-GOAL",),
          preconditions: dict[str, Any] | None = None, forbidden: dict[str, Any] | None = None, verification: tuple[str, ...] = ("public_test", "hidden_acceptance"),
          policy: bool = False) -> dict[str, Any]:
    return {"obligation_id": identifier, "kind": kind, "subject": subject, "source_requirement_refs": refs,
            "preconditions": preconditions or {}, "operation": {}, "expected": expected, "forbidden": forbidden or {},
            "dependency_policy": NOTES_DEPENDENCY_POLICY.as_dict() if policy else None,
            "verification_method": verification, "scope": ("local_json_notes",),
            "provenance": {"compiler": "notes_requirement_compiler@1", "authority": "public_contract"}}


def _specs() -> tuple[dict[str, Any], ...]:
    a = lambda i: ("REQ-NOTES-GOAL", f"REQ-NOTES-ACCEPT-{i:02d}")
    return (
        _spec("OBL-NOTES-ADD", "BEHAVIOR", "add a note and print its ID", {"stdout": "<id>\\n"}, refs=a(1)),
        _spec("OBL-NOTES-ADD-TAG", "BEHAVIOR", "add an optional exact tag", {"tag": "preserved"}, refs=a(1)),
        _spec("OBL-NOTES-ID-MONOTONIC", "STATE_TRANSITION", "allocate monotonic IDs that are never reused", {"after_delete_then_add": 3}, refs=a(1)),
        _spec("OBL-NOTES-PERSISTENCE", "PERSISTENCE", "persist state in current-directory notes.json", {"path": "notes.json", "format": "JSON"}, refs=a(1)),
        _spec("OBL-NOTES-LIST", "BEHAVIOR", "list notes with exact tab-separated output", {"stdout": "<id>\\t<text>\\t<tag-or-empty>\\n"}, refs=a(2)),
        _spec("OBL-NOTES-LIST-STABLE", "BEHAVIOR", "list notes in ascending ID order", {"order": "ascending_id"}, refs=a(2)),
        _spec("OBL-NOTES-LIST-TAG", "BEHAVIOR", "filter list by exact tag equality", {"tag_match": "exact"}, refs=a(2)),
        _spec("OBL-NOTES-SHOW", "BEHAVIOR", "show one note by positional ID", {"stdout": "<id>\\t<text>\\t<tag-or-empty>\\n"}, refs=a(3)),
        _spec("OBL-NOTES-DELETE", "STATE_TRANSITION", "delete one note by positional ID", {"stdout": "deleted <id>\\n"}, refs=a(3)),
        _spec("OBL-NOTES-DELETE-PERSISTS", "PERSISTENCE", "persist deletion across processes", {"deleted_note": "absent"}, refs=a(3)),
        _spec("OBL-NOTES-ERR-MISSING-ID", "ERROR_SEMANTICS", "reject a missing note ID", {"exit_code": "nonzero", "stderr": "nonempty"}, refs=a(4), preconditions={"note_id_exists": False}),
        _spec("OBL-NOTES-ERR-INVALID-ID", "ERROR_SEMANTICS", "reject a non-integer ID", {"exit_code": "nonzero", "stderr": "nonempty"}, refs=a(4), preconditions={"note_id_is_integer": False}),
        _spec("OBL-NOTES-CLI-HELP", "INTERFACE", "provide argparse subcommand help", {"exit_code": 0}, refs=a(4), forbidden={"commands": ["create", "remove", "get", "ls", "new"], "options": ["--id"]}),
        _spec("OBL-NOTES-README", "DOCUMENTATION", "document the exact public CLI", {"commands_documented": True}, refs=a(5), verification=("static_inspection",)),
        _spec("OBL-NOTES-RUNTIME-STDLIB", "DEPENDENCY_POLICY", "runtime dependencies are standard-library only", {"runtime_stdlib_only": True}, refs=("REQ-NOTES-POLICY-RUNTIME",), verification=("dependency_scan",), policy=True),
        _spec("OBL-NOTES-TEST-PYTEST", "DEPENDENCY_POLICY", "pytest is permitted only for tests and tooling", {"test_pytest_allowed": True}, refs=("REQ-NOTES-POLICY-TEST",), verification=("dependency_scan",), policy=True),
        _spec("OBL-NOTES-NETWORK-OFFLINE", "RESOURCE_BOUNDARY", "forbid outbound network access", {"network_outbound": "FORBIDDEN"}, refs=("REQ-NOTES-POLICY-NETWORK",), verification=("network_guard",), policy=True),
    )


def compile_local_json_notes(*, hidden_manifest: str | Path | None = None) -> NotesRequirementCompilation:
    sources = _sources()
    requirements = RequirementCompiler().normalize(sources, tuple(x.source_id for x in sources if "ACCEPT" in x.source_id))
    obligations = RequirementCompiler().compile(requirements, _specs())
    public = tuple(TestBinding("TEST-PUBLIC-" + item.obligation_id.removeprefix("OBL-"), (item.obligation_id,))
                   for item in obligations.obligations if "public_test" in item.verification_method)
    path = Path(hidden_manifest) if hidden_manifest else Path(__file__).parents[3] / "benchmarks" / "real_project_generation" / "acceptance" / "local_json_notes.obligations.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    hidden = tuple(TestBinding(str(x["test_id"]), tuple(x["obligation_ids"]), hidden=True) for x in document["tests"])
    graph = build_traceability(requirements, obligations, tests=public + hidden)
    validation = ObligationCompletenessValidator().validate(requirements, obligations)
    trace = validate_traceability(requirements, obligations, graph)
    coverage = {"coverage": trace.hidden_acceptance_coverage, "status": trace.status, "test_count": len(hidden),
                "bound_obligation_ids": sorted({oid for binding in hidden for oid in binding.obligation_ids})}
    receipt = ObligationPreflightReceipt.build(requirements, obligations, validation, trace, hidden_coverage=coverage)
    return NotesRequirementCompilation(requirements, obligations, graph, receipt)
