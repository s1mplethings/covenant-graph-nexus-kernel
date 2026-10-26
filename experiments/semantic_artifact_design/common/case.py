from __future__ import annotations

from dataclasses import dataclass

from cgkn.application.software_project.catalog import ProjectCase, get_case


@dataclass(frozen=True)
class WorkUnit:
    unit_id: str
    role: str
    paths: tuple[str, ...]
    responsibilities: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    public_interfaces: tuple[str, ...] = ()
    allowed_changes: tuple[str, ...] = ("create", "patch")

    def as_payload(self) -> dict[str, object]:
        return {"unit_id": self.unit_id, "role": self.role, "paths": list(self.paths), "responsibilities": list(self.responsibilities),
                "dependencies": list(self.dependencies), "public_interfaces": list(self.public_interfaces), "allowed_changes": list(self.allowed_changes)}


CLI_UNITS = (
    WorkUnit("cli-core", "source", ("csv_cleaner/__init__.py", "csv_cleaner/__main__.py", "csv_cleaner/core.py"),
             ("implement CSV cleaning", "provide python -m csv_cleaner entrypoint", "preserve stable public clean_csv interface"), (),
             ("csv_cleaner.core.clean_csv", "python -m csv_cleaner")),
    WorkUnit("public-tests", "tests", ("tests/test_csv_cleaner.py",),
             ("test the public CSV cleaner contract", "use structurally valid CSV fixtures"), ("cli-core",)),
    WorkUnit("documentation", "documentation", ("README.md",),
             ("document installation-free usage", "document CLI flags and examples"), ("cli-core",)),
)

REPAIR_UNITS = (
    WorkUnit("repair-core", "source", ("math_utils.py",), ("repair add without changing its public signature",), (), ("math_utils.add",), ("patch",)),
)


def case_and_units(case_id: str) -> tuple[ProjectCase, tuple[WorkUnit, ...]]:
    case = get_case(case_id)
    if case_id == "cli_csv_cleaner":
        return case, CLI_UNITS
    if case_id == "seeded_repair":
        return case, REPAIR_UNITS
    raise ValueError("semantic experiment only supports CLI and seeded repair")


def project_contract(case: ProjectCase) -> dict[str, object]:
    return {"project_id": case.case_id, "public_goal": case.public_goal,
            "constraints": ["stdlib-only", "no network", "no hidden acceptance access", "project-relative paths", "no placeholders"],
            "required_entrypoints": [case.entrypoint], "public_acceptance": list(case.public_acceptance),
            "runtime_requirements": ["real compile", "real pytest", "real runtime smoke", "external hidden acceptance"]}


def structure_payload(units: tuple[WorkUnit, ...]) -> dict[str, object]:
    return {"units": [{"unit_id": item.unit_id, "role": item.role, "paths": list(item.paths)} for item in units]}
