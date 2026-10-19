from __future__ import annotations

import json
import pathlib
import shutil
import sys

import pytest
from jsonschema import Draft202012Validator

from cgkn.application.project_blueprint import (
    BlueprintCheck, BlueprintUnit, FailureReport, FileBundle, PatchBundle,
    MINIMAL_BLUEPRINT_DESIGN_SCHEMA, MinimalBlueprintDesignPayload,
    ProjectBlueprint, apply_blueprint_edits, assemble_project_blueprint,
    extract_python_interface, interface_breaks,
)
from cgkn.application.project_loop import compile_blueprint
from cgkn.application.software_project.contracts import MAX_COHESIVE_WRITE_FILES, WorkerScope


def _unit(unit_id: str = "core", *, owns: tuple[str, ...] = ("pkg/core.py",), depends: tuple[str, ...] = ()) -> BlueprintUnit:
    return BlueprintUnit(unit_id, "implement", "implementation", owns, depends_on=depends, executor_ref="llm.cheap@1", instruction="implement", required_interfaces=("clean",), acceptance=("works",), allowed_effects=("filesystem.write",))


def _draft(*units: BlueprintUnit) -> ProjectBlueprint:
    return ProjectBlueprint("1.0", "demo", 1, "goal", ("offline",), units, ())


def test_blueprint_round_trip_hash_freeze_and_compile() -> None:
    draft = _draft(_unit())
    frozen = apply_blueprint_edits(draft, [
        {"operation": "add_check", "payload": {"check_id": "verify", "kind": "verification", "command": [sys.executable, "-m", "compileall", "-q", "."], "depends_on": ["core"], "acceptance": ["syntax"]}},
        {"operation": "add_check", "payload": {"check_id": "accept", "kind": "acceptance", "depends_on": ["verify"], "acceptance": ["hidden"]}},
        {"operation": "finish_design", "payload": {}},
    ])
    restored = ProjectBlueprint.from_dict(frozen.as_dict())
    assert restored == frozen
    assert restored.blueprint_hash.startswith("sha256:")
    tree = compile_blueprint(restored, case_id="cli_csv_cleaner")
    assert [node.id for node in tree.nodes] == ["core", "verify", "accept"]


@pytest.mark.parametrize("units,error", [
    ((_unit(), _unit()), "duplicate unit"),
    ((_unit("a"), _unit("b")), "ownership collision"),
    ((_unit("a", owns=("a.py",), depends=("b",)), _unit("b", owns=("b.py",), depends=("a",))), "cycle"),
])
def test_blueprint_rejects_invalid_structure(units, error) -> None:
    with pytest.raises(ValueError, match=error): _draft(*units)


def test_freeze_requires_acceptance_and_edit_is_atomic() -> None:
    draft = _draft(_unit())
    with pytest.raises(ValueError, match="acceptance"):
        apply_blueprint_edits(draft, [{"operation": "finish_design", "payload": {}}])
    with pytest.raises(ValueError):
        apply_blueprint_edits(draft, [{"operation": "set_goal", "payload": {"goal": "changed"}}, {"operation": "add_unit", "payload": _unit().as_dict()}])
    assert draft.goal == "goal" and len(draft.units) == 1


def test_file_and_patch_bundles_are_strict_and_mutually_exclusive() -> None:
    file_value = {"schema_version": "1.0", "kind": "file_bundle", "unit_id": "core", "files": [{"path": "a.py", "content": "x=1\n"}], "summary": "ok", "needs_escalation": False, "escalation_reason": ""}
    assert FileBundle.from_dict(file_value).files == (("a.py", "x=1\n"),)
    compact = {"schema_version": "2.0", "kind": "file_bundle", "unit_id": "core", "files": [{"path": "a.py", "content": "x=1\n"}]}
    parsed = FileBundle.from_dict(compact)
    assert parsed.files == (("a.py", "x=1\n"),) and parsed.schema_version == "2.0" and parsed.summary == ""
    with pytest.raises(ValueError): PatchBundle.from_dict(file_value)
    patch_value = {"schema_version": "1.0", "kind": "patch_bundle", "unit_id": "core", "patches": [{"path": "a.py", "find": "1", "replace": "2"}], "summary": "fix", "needs_escalation": False, "escalation_reason": ""}
    assert PatchBundle.from_dict(patch_value).patches[0][1:] == ("1", "2")


def test_interface_extractor_is_stable_and_guard_detects_breaks() -> None:
    source = "import csv\n__all__=['clean']\ndef clean(path, fill=None):\n return path\nif __name__ == '__main__':\n print('--fill')\n"
    first = extract_python_interface(source, "pkg.core")
    second = extract_python_interface(source, "pkg.core")
    assert first.manifest_hash == second.manifest_hash
    changed = extract_python_interface("def renamed(path):\n return path\n", "pkg.core")
    assert "public function removed: clean" in interface_breaks(first, changed, ("clean",))
    assert "entrypoint main guard removed" in interface_breaks(first, changed)


def test_failure_report_is_hashable_and_versioned_by_content() -> None:
    report = FailureReport("core", "TEST_FAILURE", failed_check="pytest", affected_units=("core", "pytest"))
    assert hash(report)
    assert report.failure_hash.startswith("sha256:")


def _minimal_payload(*, units: list[dict] | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "units": units or [
            {
                "unit_id": "implementation", "kind": "implementation",
                "purpose": "implement CLI", "owns": ["pkg/__init__.py", "pkg/__main__.py"],
                "reads": [], "depends_on": [], "instruction": "implement public behavior",
                "required_interfaces": ["main"], "acceptance": ["CLI works"],
            },
            {
                "unit_id": "tests", "kind": "tests", "purpose": "test CLI",
                "owns": ["tests/test_cli.py"], "reads": ["pkg/__main__.py"],
                "depends_on": [], "instruction": "test public behavior", "acceptance": ["pytest passes"],
                "required_interfaces": [],
            },
            {
                "unit_id": "docs", "kind": "documentation", "purpose": "document CLI",
                "owns": ["README.md"], "reads": [], "depends_on": [], "instruction": "document usage",
                "required_interfaces": [],
                "acceptance": ["README covers usage"],
            },
        ],
        "finish_design": True,
    }


def _public_contract() -> dict:
    return {
        "public_goal": "Build a tested CLI with README",
        "public_acceptance": ["CLI behavior", "README and tests"],
        "entrypoint": "pkg/__main__.py",
        "runtime_command": ["python", "-m", "pkg", "--help"],
        "constraints": ["stdlib only", "offline"],
    }


def test_minimal_payload_round_trip_and_strict_schema() -> None:
    value = _minimal_payload()
    payload = MinimalBlueprintDesignPayload.from_dict(value)
    assert payload.as_dict() == value
    Draft202012Validator(MINIMAL_BLUEPRINT_DESIGN_SCHEMA).validate(value)
    invalid = json.loads(json.dumps(value)); invalid["units"][0]["executor_ref"] = "llm.cheap@1"
    assert not Draft202012Validator(MINIMAL_BLUEPRINT_DESIGN_SCHEMA).is_valid(invalid)


def test_assembler_expands_defaults_checks_and_stable_hash() -> None:
    first = assemble_project_blueprint("demo", _minimal_payload(), _public_contract())
    second = assemble_project_blueprint("demo", _minimal_payload(), _public_contract())
    assert first == second and first.blueprint_hash == second.blueprint_hash
    assert [item.check_id for item in first.checks] == ["compile", "pytest", "runtime_smoke", "external_acceptance"]
    assert first.by_id["tests"].depends_on == ("implementation",)
    assert all(item.executor_ref == "llm.cheap@1" for item in first.units)
    assert all(item.status == "PENDING" and item.timeout_seconds == 120 for item in first.units)
    assert all(item.protected_paths for item in first.units)


@pytest.mark.parametrize(
    ("units", "message"),
    [
        ([
            {"unit_id": "implementation", "kind": "implementation", "purpose": "x", "owns": ["../x.py"], "depends_on": [], "instruction": "x", "acceptance": ["x"]},
            {"unit_id": "tests", "kind": "tests", "purpose": "x", "owns": ["tests/test_x.py"], "depends_on": ["implementation"], "instruction": "x", "acceptance": ["x"]},
        ], "unsafe"),
        ([
            {"unit_id": "implementation", "kind": "implementation", "purpose": "x", "owns": ["pkg/__main__.py"], "depends_on": [], "instruction": "x", "acceptance": ["x"]},
            {"unit_id": "tests", "kind": "tests", "purpose": "x", "owns": ["pkg/__main__.py"], "depends_on": ["implementation"], "instruction": "x", "acceptance": ["x"]},
        ], "ownership collision"),
        ([
            {"unit_id": "implementation", "kind": "implementation", "purpose": "x", "owns": ["pkg/__main__.py"], "depends_on": ["missing"], "instruction": "x", "acceptance": ["x"]},
            {"unit_id": "tests", "kind": "tests", "purpose": "x", "owns": ["tests/test_x.py"], "depends_on": ["implementation"], "instruction": "x", "acceptance": ["x"]},
        ], "invalid dependency"),
        ([
            {"unit_id": "implementation", "kind": "implementation", "purpose": "x", "owns": ["pkg/__main__.py"], "depends_on": ["tests"], "instruction": "x", "acceptance": ["x"]},
            {"unit_id": "tests", "kind": "tests", "purpose": "x", "owns": ["tests/test_x.py"], "depends_on": ["implementation"], "instruction": "x", "acceptance": ["x"]},
        ], "cycle"),
    ],
)
def test_assembler_rejects_invalid_paths_ownership_and_dependencies(units, message) -> None:
    contract = _public_contract()
    contract["public_goal"] = "Build a tested CLI"
    contract["public_acceptance"] = ["CLI behavior", "tests"]
    with pytest.raises(ValueError, match=message):
        assemble_project_blueprint("demo", _minimal_payload(units=units), contract)


def test_assembler_requires_tests_and_readme_coverage() -> None:
    implementation = _minimal_payload()["units"][0]
    docs = _minimal_payload()["units"][2]
    with pytest.raises(ValueError, match="tests coverage"):
        assemble_project_blueprint("demo", _minimal_payload(units=[implementation, docs]), _public_contract())
    tests = _minimal_payload()["units"][1]
    with pytest.raises(ValueError, match="README coverage"):
        assemble_project_blueprint("demo", _minimal_payload(units=[implementation, tests]), _public_contract())


def test_minimal_payload_rejects_unit_and_file_count_limits() -> None:
    base = _minimal_payload()["units"]
    with pytest.raises(ValueError, match="two to four"):
        MinimalBlueprintDesignPayload.from_dict(_minimal_payload(units=base + [dict(base[2], unit_id="docs2", owns=["DOCS.md"]), dict(base[2], unit_id="docs3", owns=["GUIDE.md"])]))
    too_many = dict(base[0], owns=[f"pkg/f{i}.py" for i in range(6)])
    with pytest.raises(ValueError, match="one to five"):
        MinimalBlueprintDesignPayload.from_dict(_minimal_payload(units=[too_many, base[1], base[2]]))


def test_frozen_blueprint_worker_scope_contract_is_monotonic() -> None:
    owns = tuple(f"pkg/file_{index}.py" for index in range(4))
    unit = BlueprintUnit(
        "core", "cohesive implementation", "implementation", owns,
        reads=("contracts/public.py", "deps/types.py"), executor_ref="llm.cheap@1",
        instruction="implement", acceptance=("works",), allowed_effects=("filesystem.read", "filesystem.write"),
        max_files=4,
    )
    blueprint = ProjectBlueprint(
        "1.0", "scope-contract", 1, "goal", ("offline",), (unit,),
        (BlueprintCheck("accept", "acceptance", depends_on=("core",), acceptance=("hidden",)),),
    ).freeze()
    compiled = compile_blueprint(blueprint)
    compiled_unit = BlueprintUnit.from_dict(compiled.nodes[0].config["unit"])
    try:
        scope = WorkerScope(
            compiled_unit.owns + compiled_unit.reads,
            compiled_unit.owns,
            max_write_files=compiled_unit.max_files,
        )
    except ValueError as exc:
        pytest.fail(f"BLUEPRINT_WORKER_SCOPE_CONTRACT_MISMATCH: {exc}")
    assert len(scope.writable_paths) == 4

    with pytest.raises(ValueError, match="max_files"):
        BlueprintUnit(
            "too-wide", "too wide", "implementation",
            tuple(f"pkg/f{index}.py" for index in range(MAX_COHESIVE_WRITE_FILES + 1)),
            executor_ref="llm.cheap@1", instruction="implement", acceptance=("works",),
            allowed_effects=("filesystem.write",), max_files=MAX_COHESIVE_WRITE_FILES + 1,
        )
    with pytest.raises(ValueError, match="at most five"):
        BlueprintUnit(
            "underdeclared", "underdeclared", "implementation", owns,
            executor_ref="llm.cheap@1", instruction="implement", acceptance=("works",),
            allowed_effects=("filesystem.write",), max_files=3,
        )
