from __future__ import annotations

import json
import pathlib
import shutil
import sys

import pytest

from cgkn.application.project_blueprint import (
    BlueprintCheck, BlueprintUnit, FailureReport, FileBundle, PatchBundle,
    ProjectBlueprint, apply_blueprint_edits, extract_python_interface, interface_breaks,
)
from cgkn.application.project_loop import compile_blueprint


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
