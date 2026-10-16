from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .csv import CSVRequirementCompilation


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
        ),
        WorkUnitContract(
            "WU-TESTS", tuple(sorted(identifier for identifier in known if identifier not in {"OBL-CSV-README"})),
            ("tests/test_csv_cleaner.py",), ("csv_cleaner/__init__.py", "csv_cleaner/__main__.py", "csv_cleaner/core.py"),
            ("implement the supplied TestPlan without adding behavior",), (), (), policy,
            ("filesystem.read", "filesystem.write"), hidden_refs, ("WU-CORE",),
        ),
        WorkUnitContract(
            "WU-DOCS", ("OBL-CSV-README", "OBL-CSV-CLI-HELP"), ("README.md",),
            ("csv_cleaner/__main__.py",), ("document the declared CLI and examples",),
            ("python -m csv_cleaner",), (), policy, ("filesystem.read", "filesystem.write"), hidden_refs,
            ("WU-CORE",),
        ),
    )
