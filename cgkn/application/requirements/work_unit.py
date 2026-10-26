from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .csv import CSVRequirementCompilation
from .notes import NotesRequirementCompilation


@dataclass(frozen=True)
class WorkUnitContract:
    work_unit_id: str
    obligation_ids: tuple[str, ...]
    target_paths: tuple[str, ...]
    allowed_read_paths: tuple[str, ...]
    responsibilities: tuple[str, ...]
    required_interfaces: tuple[str, ...]
    preserved_interfaces: tuple[str, ...]
    dependency_policy_refs: tuple[str, ...]
    allowed_effects: tuple[str, ...]
    acceptance_refs: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    interface_contract_refs: tuple[str, ...] = ()
    schema_version: str = "1.0"

    def __post_init__(self) -> None:
        if not self.work_unit_id or not self.obligation_ids or not self.target_paths:
            raise ValueError("work unit requires identity, obligations, and targets")
        if len(set(self.target_paths)) != len(self.target_paths):
            raise ValueError("duplicate work-unit target")
        if any(effect not in {"filesystem.read", "filesystem.write"} for effect in self.allowed_effects):
            raise ValueError("unsupported work-unit effect")

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": "CGKNWorkUnitContract", "schema_version": self.schema_version,
            "work_unit_id": self.work_unit_id, "obligation_ids": list(self.obligation_ids),
            "target_paths": list(self.target_paths), "allowed_read_paths": list(self.allowed_read_paths),
            "responsibilities": list(self.responsibilities), "required_interfaces": list(self.required_interfaces),
            "preserved_interfaces": list(self.preserved_interfaces), "dependency_policy_refs": list(self.dependency_policy_refs),
            "allowed_effects": list(self.allowed_effects), "acceptance_refs": list(self.acceptance_refs),
            "depends_on": list(self.depends_on),
            "interface_contract_refs": list(self.interface_contract_refs),
        }


def compile_csv_work_units(compilation: CSVRequirementCompilation) -> tuple[WorkUnitContract, ...]:
    known = {item.obligation_id for item in compilation.obligations.obligations}
    core = tuple(sorted(identifier for identifier in known if identifier not in {
        "OBL-CSV-README", "OBL-CSV-PUBLIC-TESTS", "OBL-CSV-TEST-PYTEST",
    }))
    hidden_refs = tuple(sorted(compilation.traceability.acceptance_to_obligation))
    policy = ("POLICY-CSV-DEPS-001",)
    return (
        WorkUnitContract(
            "WU-CORE", core,
            ("csv_cleaner/__init__.py", "csv_cleaner/__main__.py", "csv_cleaner/core.py"), (),
            ("implement the compiled CSV runtime obligations", "provide the module CLI entrypoint"),
            ("csv_cleaner.core.clean_csv", "python -m csv_cleaner"), (), policy,
            ("filesystem.write",), hidden_refs,
            interface_contract_refs=("INTERFACE-CSV-MODULE-001", "INTERFACE-CSV-CLEAN-FUNCTION-001", "INTERFACE-CSV-CLI-001"),
        ),
        WorkUnitContract(
            "WU-TESTS", tuple(sorted(identifier for identifier in known if identifier not in {"OBL-CSV-README"})),
            ("tests/test_csv_cleaner.py",), ("csv_cleaner/__init__.py", "csv_cleaner/__main__.py", "csv_cleaner/core.py"),
            ("implement the supplied TestPlan without adding behavior",), (), (), policy,
            ("filesystem.read", "filesystem.write"), hidden_refs, ("WU-CORE",),
        ),
        WorkUnitContract(
            "WU-DOCS", ("OBL-CSV-README", "OBL-CSV-CLI-HELP"), ("README.md",),
            (), ("document the canonical CLI interface contract and examples",),
            ("python -m csv_cleaner",), (), policy, ("filesystem.write",), hidden_refs,
            (),
            interface_contract_refs=("INTERFACE-CSV-CLI-001",),
        ),
    )


def compile_notes_work_units(compilation: NotesRequirementCompilation) -> tuple[WorkUnitContract, ...]:
    known = {item.obligation_id for item in compilation.obligations.obligations}
    hidden_refs = tuple(sorted(compilation.traceability.acceptance_to_obligation))
    policy = ("POLICY-NOTES-DEPS-001",)
    core_excluded = {"OBL-NOTES-CLI-HELP", "OBL-NOTES-README", "OBL-NOTES-TEST-PYTEST"}
    return (
        WorkUnitContract(
            "WU-CORE", tuple(sorted(known - core_excluded)),
            ("notes/__init__.py", "notes/model.py", "notes/store.py", "notes/service.py"), (),
            ("implement persistent JSON note state", "preserve monotonic IDs and exact tag semantics"),
            ("notes.service.add_note", "notes.service.list_notes", "notes.service.show_note", "notes.service.delete_note"),
            (), policy, ("filesystem.write",), hidden_refs,
            interface_contract_refs=("INTERFACE-NOTES-ADD-001", "INTERFACE-NOTES-LIST-001", "INTERFACE-NOTES-SHOW-001", "INTERFACE-NOTES-DELETE-001"),
        ),
        WorkUnitContract(
            "WU-CLI", ("OBL-NOTES-ADD", "OBL-NOTES-ADD-TAG", "OBL-NOTES-LIST", "OBL-NOTES-LIST-STABLE", "OBL-NOTES-LIST-TAG",
                       "OBL-NOTES-SHOW", "OBL-NOTES-DELETE", "OBL-NOTES-CLI-HELP", "OBL-NOTES-ERR-INVALID-ID", "OBL-NOTES-ERR-MISSING-ID"),
            ("notes/__main__.py",), (), ("implement the exact canonical argparse subcommands",),
            ("python -m notes",), (), policy, ("filesystem.write",), hidden_refs, (),
            interface_contract_refs=("INTERFACE-NOTES-CLI-001",),
        ),
        WorkUnitContract(
            "WU-DOCS", ("OBL-NOTES-README", "OBL-NOTES-CLI-HELP"), ("README.md",), (),
            ("document the canonical Notes CLI and output contract",), ("python -m notes",), (), policy,
            ("filesystem.write",), hidden_refs, (), interface_contract_refs=("INTERFACE-NOTES-CLI-001",),
        ),
    )
