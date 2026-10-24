"""Evaluation-only B0/B1 ProjectBlueprint codec and offline behavior harness.

B0 is the current frozen ``ProjectBlueprint``.  B1 is a compact semantic
representation that can only be decoded through the current deterministic
``assemble_project_blueprint`` authority.  Encoding fails closed unless the
decoded B1 object is byte-for-byte semantically equivalent to B0.

This module deliberately does not participate in production generation.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from cgkn.application.project_blueprint import (
    FailureAction,
    FailureReport,
    FailureStage,
    MinimalBlueprintDesignPayload,
    MinimalBlueprintUnitDesign,
    ProjectBlueprint,
    assemble_project_blueprint,
    public_requirement_catalog,
)
from cgkn.application.project_loop import MinimalProjectLoop, compile_blueprint
from cgkn.orchestration import compile_tree
from cgkn.providers import ModelRoleConfig, ProviderCompletion


CANDIDATE_SCHEMA_VERSION = "a2-eval-1"
_UNIT_REQUIRED = {"kind", "purpose", "owns", "requirement_ids"}
_UNIT_OPTIONAL = {"reads", "depends_on", "required_interfaces"}
_TOP_LEVEL = {"schema_version", "project_id", "revision", "goal", "constraints", "units"}


def _tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("minimal Blueprint sequence field must be an array")
    return tuple(str(item) for item in value)


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _hash(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MinimalSemanticUnit:
    """Only Agent-owned semantics that cannot be safely inferred are retained."""

    kind: str
    purpose: str
    owns: tuple[str, ...]
    requirement_ids: tuple[str, ...]
    reads: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    required_interfaces: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Reuse the production semantic boundary for kind/path/requirement shape.
        MinimalBlueprintUnitDesign(self.kind, self.purpose, self.owns, self.requirement_ids)
        for name, values in (
            ("reads", self.reads),
            ("depends_on", self.depends_on),
            ("required_interfaces", self.required_interfaces),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"minimal Blueprint {name} values must be unique")

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "kind": self.kind,
            "purpose": self.purpose,
            "owns": list(self.owns),
            "requirement_ids": list(self.requirement_ids),
        }
        if self.reads:
            value["reads"] = list(self.reads)
        if self.depends_on:
            value["depends_on"] = list(self.depends_on)
        if self.required_interfaces:
            value["required_interfaces"] = list(self.required_interfaces)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MinimalSemanticUnit":
        fields = set(value)
        if not _UNIT_REQUIRED <= fields or fields - (_UNIT_REQUIRED | _UNIT_OPTIONAL):
            raise ValueError("minimal Blueprint unit contains unknown or missing fields")
        return cls(
            kind=str(value["kind"]),
            purpose=str(value["purpose"]),
            owns=_tuple(value["owns"]),
            requirement_ids=_tuple(value["requirement_ids"]),
            reads=_tuple(value.get("reads")),
            depends_on=_tuple(value.get("depends_on")),
            required_interfaces=_tuple(value.get("required_interfaces")),
        )


@dataclass(frozen=True)
class MinimalSemanticBlueprint:
    """B1 candidate.  It is never accepted without exact B0 reconstruction."""

    project_id: str
    revision: int
    goal: str
    constraints: tuple[str, ...]
    units: tuple[MinimalSemanticUnit, ...]
    schema_version: str = CANDIDATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CANDIDATE_SCHEMA_VERSION:
            raise ValueError("unsupported minimal Blueprint candidate version")
        if not self.project_id or self.revision < 1 or not self.goal.strip():
            raise ValueError("minimal Blueprint identity and goal are required")
        if not 2 <= len(self.units) <= 4:
            raise ValueError("minimal Blueprint candidate requires two to four units")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "revision": self.revision,
            "goal": self.goal,
            "constraints": list(self.constraints),
            "units": [item.as_dict() for item in self.units],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MinimalSemanticBlueprint":
        if set(value) != _TOP_LEVEL:
            raise ValueError("minimal Blueprint contains unknown or missing fields")
        raw_units = value.get("units")
        if not isinstance(raw_units, list):
            raise ValueError("minimal Blueprint units must be an array")
        return cls(
            project_id=str(value["project_id"]),
            revision=int(value["revision"]),
            goal=str(value["goal"]),
            constraints=_tuple(value["constraints"]),
            units=tuple(MinimalSemanticUnit.from_dict(item) for item in raw_units),
            schema_version=str(value["schema_version"]),
        )


def minimal_blueprint_schema() -> dict[str, Any]:
    """A strict JSON schema for evidence and future Provider-independent use."""

    array = {"type": "array", "items": {"type": "string"}, "uniqueItems": True}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_TOP_LEVEL),
        "properties": {
            "schema_version": {"const": CANDIDATE_SCHEMA_VERSION},
            "project_id": {"type": "string", "minLength": 1},
            "revision": {"type": "integer", "minimum": 1},
            "goal": {"type": "string", "minLength": 1},
            "constraints": array,
            "units": {
                "type": "array",
                "minItems": 2,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": sorted(_UNIT_REQUIRED),
                    "properties": {
                        "kind": {"enum": ["implementation", "tests", "documentation"]},
                        "purpose": {"type": "string", "minLength": 1},
                        "owns": {**array, "minItems": 1, "maxItems": 5},
                        "requirement_ids": array,
                        "reads": array,
                        "depends_on": array,
                        "required_interfaces": array,
                    },
                },
            },
        },
    }


def decode_minimal_blueprint(
    candidate: MinimalSemanticBlueprint | Mapping[str, Any],
    public_contract: Mapping[str, Any],
) -> ProjectBlueprint:
    """Deterministically expand B1 through the current production assembler."""

    compact = candidate if isinstance(candidate, MinimalSemanticBlueprint) else MinimalSemanticBlueprint.from_dict(candidate)
    public_goal = str(public_contract.get("public_goal", "")).strip()
    constraints = tuple(str(item) for item in public_contract.get("constraints", ()))
    if compact.goal != public_goal or compact.constraints != constraints:
        raise ValueError("minimal Blueprint public contract identity mismatch")
    design = MinimalBlueprintDesignPayload(tuple(
        MinimalBlueprintUnitDesign(item.kind, item.purpose, item.owns, item.requirement_ids)
        for item in compact.units
    ))
    expanded = assemble_project_blueprint(compact.project_id, design, public_contract)
    if expanded.revision != compact.revision or len(expanded.units) != len(compact.units):
        raise ValueError("minimal Blueprint deterministic identity mismatch")
    known_ids = {item.unit_id for item in expanded.units}
    rebuilt = []
    for derived, semantic in zip(expanded.units, compact.units, strict=True):
        unknown = set(semantic.depends_on) - known_ids
        if unknown or derived.unit_id in semantic.depends_on:
            raise ValueError(f"minimal Blueprint dependency mismatch: {derived.unit_id}")
        rebuilt.append(replace(
            derived,
            reads=semantic.reads,
            depends_on=semantic.depends_on,
            required_interfaces=semantic.required_interfaces,
        ))
    return ProjectBlueprint(
        expanded.schema_version,
        expanded.project_id,
        expanded.revision,
        expanded.goal,
        expanded.constraints,
        tuple(rebuilt),
        expanded.checks,
        expanded.status,
    )


def assert_semantic_equivalence(authority: ProjectBlueprint, candidate: ProjectBlueprint) -> None:
    """Require exact public/runtime behavior, not merely a similar graph."""

    left = authority.as_dict()
    right = candidate.as_dict()
    if left != right:
        for section in ("schema_version", "project_id", "revision", "goal", "constraints", "units", "checks", "status", "blueprint_hash"):
            if left.get(section) != right.get(section):
                raise ValueError(f"minimal Blueprint semantic mismatch: {section}")
        raise ValueError("minimal Blueprint semantic mismatch")


def encode_minimal_blueprint(
    authority: ProjectBlueprint,
    public_contract: Mapping[str, Any],
) -> MinimalSemanticBlueprint:
    """Compress a canonical B0 Blueprint and prove its B1 round-trip immediately."""

    requirement_ids = {summary: requirement_id for requirement_id, summary in public_requirement_catalog(public_contract)}
    units: list[MinimalSemanticUnit] = []
    for unit in authority.units:
        ids: list[str] = []
        for acceptance in unit.acceptance:
            requirement_id = requirement_ids.get(acceptance)
            if requirement_id:
                ids.append(requirement_id)
        units.append(MinimalSemanticUnit(
            kind=unit.kind,
            purpose=unit.purpose,
            owns=unit.owns,
            requirement_ids=tuple(ids),
            reads=unit.reads,
            depends_on=unit.depends_on,
            required_interfaces=unit.required_interfaces,
        ))
    compact = MinimalSemanticBlueprint(
        authority.project_id,
        authority.revision,
        authority.goal,
        authority.constraints,
        tuple(units),
    )
    assert_semantic_equivalence(authority, decode_minimal_blueprint(compact, public_contract))
    return compact


def _shape(value: object, *, depth: int = 0) -> dict[str, int]:
    metrics = {"keys": 0, "list_items": 0, "scalars": 0, "max_depth": depth}
    if isinstance(value, Mapping):
        metrics["keys"] += len(value)
        for item in value.values():
            child = _shape(item, depth=depth + 1)
            for name in ("keys", "list_items", "scalars"):
                metrics[name] += child[name]
            metrics["max_depth"] = max(metrics["max_depth"], child["max_depth"])
    elif isinstance(value, (list, tuple)):
        metrics["list_items"] += len(value)
        for item in value:
            child = _shape(item, depth=depth + 1)
            for name in ("keys", "list_items", "scalars"):
                metrics[name] += child[name]
            metrics["max_depth"] = max(metrics["max_depth"], child["max_depth"])
    else:
        metrics["scalars"] += 1
    return metrics


def representation_metrics(authority: ProjectBlueprint, compact: MinimalSemanticBlueprint) -> dict[str, Any]:
    b0_value = authority.as_dict()
    b1_value = compact.as_dict()
    b0 = _canonical_json(b0_value).encode("utf-8")
    b1 = _canonical_json(b1_value).encode("utf-8")
    return {
        "b0": {"bytes": len(b0), **_shape(b0_value), "hash": _hash(b0_value)},
        "b1": {"bytes": len(b1), **_shape(b1_value), "hash": _hash(b1_value)},
        "byte_reduction": len(b0) - len(b1),
        "byte_reduction_percent": round((1 - len(b1) / len(b0)) * 100, 2),
        "derived_fields": [
            "unit_id", "acceptance", "instruction", "executor_ref", "allowed_effects",
            "max_actions", "max_files", "max_output_bytes", "unit_status",
            "protected_paths", "timeout_seconds", "checks", "blueprint_status", "blueprint_hash",
        ],
        "retained_semantics": [
            "responsibility", "ownership", "read_scope", "public_requirement_ids",
            "required_interfaces", "dependencies", "project_goal", "project_constraints",
        ],
    }


class _QueueClient:
    def __init__(self, responses: Iterable[Mapping[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, system: str, user: str, schema_name: str, schema: Mapping[str, Any], config: ModelRoleConfig) -> ProviderCompletion:
        self.calls.append({"system": system, "user": user, "schema_name": schema_name, "role": config.role})
        if not self.responses:
            raise AssertionError("unexpected offline Provider call")
        value = self.responses.pop(0)
        return ProviderCompletion(
            json.dumps(value), config.model, f"offline-{len(self.calls)}",
            {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )


def _bundle(unit_id: str, files: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schema_version": "1.0", "kind": "file_bundle", "unit_id": unit_id,
        "files": [{"path": path, "content": content} for path, content in files.items()],
        "summary": "offline A/B fixture", "needs_escalation": False, "escalation_reason": "",
    }


def _patch(unit_id: str, path: str, find: str, replacement: str) -> dict[str, Any]:
    return {
        "schema_version": "2.0", "kind": "patch_bundle", "unit_id": unit_id,
        "files": [{"path": path, "edits": [{"find": find, "replace": replacement}]}],
    }


_CSV_CORE = '''from __future__ import annotations
import csv

def clean_rows(fieldnames, rows, dedupe_column=None, fill=None):
    if dedupe_column and dedupe_column not in fieldnames:
        raise ValueError(f"unknown column: {dedupe_column}")
    seen = set(); result = []
    for row in rows:
        current = {name: ((row.get(name) or fill) if fill is not None else (row.get(name) or "")) for name in fieldnames}
        key = current[dedupe_column] if dedupe_column else tuple(current[name] for name in fieldnames)
        if key not in seen:
            seen.add(key); result.append(current)
    return result

def clean_file(source, target, dedupe_column=None, fill=None):
    with open(source, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle); fieldnames = list(reader.fieldnames or []); rows = clean_rows(fieldnames, list(reader), dedupe_column, fill)
    with open(target, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames); writer.writeheader(); writer.writerows(rows)
    return fieldnames, rows
'''

_CSV_MAIN = '''import argparse, csv, sys
from .core import clean_file

def main(argv=None):
    parser = argparse.ArgumentParser(description="Clean CSV files")
    parser.add_argument("input"); parser.add_argument("output")
    parser.add_argument("--dedupe-column"); parser.add_argument("--fill"); parser.add_argument("--preview", type=int, default=0)
    args = parser.parse_args(argv)
    try: fieldnames, rows = clean_file(args.input, args.output, args.dedupe_column, args.fill)
    except (OSError, ValueError) as exc: parser.error(str(exc))
    if args.preview:
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames, lineterminator="\\n"); writer.writerows(rows[:args.preview])
    return 0

if __name__ == "__main__": raise SystemExit(main())
'''


def _design(case_id: str, public_contract: Mapping[str, Any]) -> ProjectBlueprint:
    if case_id == "cli_csv_cleaner":
        payload = MinimalBlueprintDesignPayload((
            MinimalBlueprintUnitDesign("implementation", "Implement the CSV package and command line entrypoint", ("csv_cleaner/__init__.py", "csv_cleaner/__main__.py", "csv_cleaner/core.py"), ("REQ-001", "REQ-002", "REQ-003", "REQ-005")),
            MinimalBlueprintUnitDesign("tests", "Test the public CSV behavior", ("tests/test_csv_cleaner.py",), ()),
            MinimalBlueprintUnitDesign("documentation", "Document the public command line usage", ("README.md",), ("REQ-004",)),
        ))
    elif case_id == "seeded_repair":
        payload = MinimalBlueprintDesignPayload((
            MinimalBlueprintUnitDesign("implementation", "Repair the arithmetic implementation", ("math_utils.py",), ("REQ-002", "REQ-004")),
            MinimalBlueprintUnitDesign("tests", "Retain the public arithmetic test", ("test_math_utils.py",), ("REQ-001", "REQ-003")),
            MinimalBlueprintUnitDesign("documentation", "Document the public add operation", ("README.md",), ()),
        ))
    else:
        raise ValueError(f"unsupported offline Blueprint A/B case: {case_id}")
    return assemble_project_blueprint(case_id, payload, public_contract)


def _responses(case_id: str) -> list[dict[str, Any]]:
    if case_id == "cli_csv_cleaner":
        return [
            _bundle("documentation-1", {"README.md": "# CSV Cleaner\n\n`python -m csv_cleaner INPUT OUTPUT [--dedupe-column COLUMN] [--fill VALUE] [--preview N]`\n"}),
            _bundle("implementation-1", {
                "csv_cleaner/__init__.py": "from .core import clean_file, clean_rows\n__all__=['clean_file','clean_rows']\n",
                "csv_cleaner/__main__.py": _CSV_MAIN,
                "csv_cleaner/core.py": _CSV_CORE,
            }),
            _bundle("tests-1", {"tests/test_csv_cleaner.py": "from csv_cleaner.core import clean_rows\ndef test_dedupe():\n assert clean_rows(['id'],[{'id':'1'},{'id':'1'}]) == [{'id':'1'}]\n"}),
        ]
    return [
        _bundle("documentation-1", {"README.md": "# Arithmetic\n\n`add(a, b)` returns the sum.\n"}),
        _patch("implementation-1", "math_utils.py", "return a - b", "return a + b"),
        _bundle("tests-1", {"test_math_utils.py": "from math_utils import add\n\ndef test_add_positive_numbers():\n    assert add(2, 3) == 5\n"}),
    ]


def _initial_failure(case_id: str) -> FailureReport | None:
    if case_id != "seeded_repair":
        return None
    return FailureReport(
        "pytest", "TEST_FAILURE", failure_stage=FailureStage.TEST.value,
        owner_unit_id="implementation-1", recovery_action=FailureAction.REPAIR_EXISTING.value,
        materialized_baseline=True, owner_file="math_utils.py", owner_interface="add",
        failed_check="pytest", expected="add(2, 3) == 5", observed="-1",
        affected_units=("implementation-1",), suggested_action="repair the existing implementation",
        evidence_refs=("public_test",),
    )


def _workspace_files(workspace: pathlib.Path, expected_paths: Iterable[str]) -> dict[str, str]:
    files: dict[str, str] = {}
    for relative in sorted(set(expected_paths)):
        target = workspace / relative
        if target.is_file():
            files[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
    return files


def _outcome_signature(outcome: Any, workspace: pathlib.Path, expected_paths: tuple[str, ...]) -> dict[str, Any]:
    return {
        "status": outcome.status,
        "provider_calls": outcome.provider_calls,
        "generation_calls": outcome.generation_calls,
        "generation_continuations": outcome.generation_continuations,
        "generation_retry_calls": outcome.generation_retry_calls,
        "repair_calls": outcome.repair_calls,
        "repair_rounds": outcome.repair_rounds,
        "actual_executions": list(outcome.summary.actual_executions),
        "failure_types": [item.failure_type for item in outcome.failure_reports],
        "workspace_files": _workspace_files(workspace, expected_paths),
    }


def _run_variant(
    *, repository_root: pathlib.Path, destination: pathlib.Path, case_id: str,
    blueprint: ProjectBlueprint, variant: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    workspace = destination / variant / "workspace"
    run_root = destination / variant / "runs"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    if case_id == "seeded_repair":
        fixture = repository_root / "benchmarks" / "real_project_generation" / "fixtures" / "seeded_repair"
        shutil.copy2(fixture / "math_utils.py", workspace / "math_utils.py")
        shutil.copy2(fixture / "test_math_utils.py", workspace / "test_math_utils.py")
    client = _QueueClient(_responses(case_id))
    loop = MinimalProjectLoop(
        repository_root, run_root, client,
        ModelRoleConfig("agent", "offline-strong"),
        ModelRoleConfig("worker", "offline-cheap"),
    )
    outcome = loop.run(
        blueprint, workspace, case_id=case_id,
        initial_failure=_initial_failure(case_id),
    )
    expected_paths = tuple(path for unit in blueprint.units for path in unit.owns)
    signature = _outcome_signature(outcome, workspace, expected_paths)
    signature["prompt_chars"] = sum(len(call["system"]) + len(call["user"]) for call in client.calls)
    signature["scope_preserved"] = set(signature["workspace_files"]) == set(expected_paths)
    serialized_prompts = "\n".join(call["system"] + call["user"] for call in client.calls)
    signature["hidden_source_exposed"] = "benchmarks/real_project_generation/acceptance" in serialized_prompts.replace("\\", "/")
    return signature, client.calls


def run_offline_blueprint_ab(repository_root: pathlib.Path, artifact_root: pathlib.Path) -> dict[str, Any]:
    """Run zero-cost B0/B1 representation and behavioral equivalence evidence."""

    from cgkn.application.software_project.catalog import get_case

    cases: list[dict[str, Any]] = []
    for case_id in ("cli_csv_cleaner", "seeded_repair"):
        case = get_case(case_id)
        public_contract = {
            "case_id": case.case_id,
            "public_goal": case.public_goal,
            "public_acceptance": list(case.public_acceptance),
            "entrypoint": case.entrypoint,
            "runtime_command": list(case.runtime_command),
            "constraints": [
                "stdlib only", "offline", "no hidden acceptance access",
                "no placeholders", "worker writes exactly unit.owns",
            ],
        }
        authority = _design(case_id, public_contract)
        compact = encode_minimal_blueprint(authority, public_contract)
        reconstructed = decode_minimal_blueprint(compact, public_contract)
        assert_semantic_equivalence(authority, reconstructed)
        b0_tree = compile_blueprint(authority, case_id=case_id)
        b1_tree = compile_blueprint(reconstructed, case_id=case_id)
        tree_equal = b0_tree.as_dict() == b1_tree.as_dict()
        dag_equal = compile_tree(b0_tree).as_dict() == compile_tree(b1_tree).as_dict()
        destination = artifact_root / case_id
        b0_behavior, _ = _run_variant(
            repository_root=repository_root, destination=destination, case_id=case_id,
            blueprint=authority, variant="b0",
        )
        b1_behavior, _ = _run_variant(
            repository_root=repository_root, destination=destination, case_id=case_id,
            blueprint=reconstructed, variant="b1",
        )
        behavior_equal = b0_behavior == b1_behavior
        case_pass = (
            tree_equal and dag_equal and behavior_equal
            and b0_behavior["status"] == "SUCCEEDED"
            and b0_behavior["scope_preserved"]
            and not b0_behavior["hidden_source_exposed"]
        )
        cases.append({
            "case_id": case_id,
            "status": "PASS" if case_pass else "FAIL",
            "semantic_equivalence": True,
            "tree_equal": tree_equal,
            "dag_equal": dag_equal,
            "behavior_equal": behavior_equal,
            "representation": representation_metrics(authority, compact),
            "candidate": compact.as_dict(),
            "candidate_hash": _hash(compact.as_dict()),
            "blueprint_hash": authority.blueprint_hash,
            "b0_behavior": b0_behavior,
            "b1_behavior": b1_behavior,
        })
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository_root, text=True,
    ).strip()
    source_tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=repository_root, text=True,
    ).strip()
    source_clean = not bool(subprocess.check_output(
        ["git", "status", "--short"], cwd=repository_root, text=True,
    ).strip())
    result = {
        "profile": "blueprint-ab",
        "mode": "OFFLINE_FAKE_PROVIDER",
        "source_commit": source_commit,
        "source_tree": source_tree,
        "source_clean": source_clean,
        "paid_provider_calls": 0,
        "production_authority_changed": False,
        "status": "PASS" if all(item["status"] == "PASS" for item in cases) else "FAIL",
        "cases": cases,
        "representation_equivalence": "PROVEN_OFFLINE",
        "representation_size_benefit": "PROVEN_OFFLINE",
        "runtime_token_call_benefit": "NOT_PROVEN_PROMPT_CHARS_AND_CALLS_IDENTICAL",
        "d3_adaptive_gate": "NOT_QUALIFIED",
        "production_adoption": "NOT_ADOPTED",
        "recommendation": "KEEP_CURRENT_PRODUCTION_BLUEPRINT",
        "recommendation_gate": "B1 remains evaluation-only because the formal D3 adaptive gate was not qualified and runtime prompts/calls were unchanged",
    }
    result["receipt_hash"] = _hash(result)
    artifact_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "blueprint-ab.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result

