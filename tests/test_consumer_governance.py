from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cgkn.governance.consumer import GovernanceEngine, GovernanceError, canonical_hash


TOOL_ROOT = Path(__file__).resolve().parents[1]


def run(cwd: Path, *argv: str) -> str:
    result = subprocess.run(list(argv), cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return result.stdout.strip()


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def fixture(tmp_path: Path) -> Path:
    project = tmp_path / "consumer"
    project.mkdir()
    run(project, "git", "init", "-b", "main")
    run(project, "git", "config", "user.email", "tests@example.test")
    run(project, "git", "config", "user.name", "CGKN Tests")
    (project / "src").mkdir()
    (project / "tests").mkdir()
    (project / "src" / "core.py").write_text("BOUNDARY = True\n", encoding="utf-8")
    (project / "tests" / "test_boundary.py").write_text("def test_boundary():\n    assert True\n", encoding="utf-8")
    invariant = {
        "id": "INV-001", "version": 1, "title": "Human gate", "description": "Keep authority",
        "severity": "constitutional", "scope": ["src/**"], "effectiveFrom": {"commit": "initial"},
        "verification": ["test:boundary"], "governedCapabilities": ["capability.demo.core"],
        "changePolicy": "requires_user_review",
    }
    capability = {
        "id": "capability.demo.core", "version": 1, "title": "Core", "description": "Core behavior",
        "guarantees": ["preserves boundary"], "dependsOn": [], "verification": ["test:boundary"],
    }
    write(project / ".cgnk/governance/manifest.json", {
        "schemaVersion": "1.0", "projectId": "demo", "governedPaths": ["src/**"], "nonGovernedPaths": [],
        "verificationTargets": {"test:boundary": {"type": "pytest", "command": [sys.executable, "-m", "pytest", "-q", "tests/test_boundary.py"], "requiredFiles": ["tests/test_boundary.py"], "collectionPattern": "1 passed"}},
    })
    write(project / ".cgnk/governance/permanent_invariants.json", {"invariants": [invariant]})
    write(project / ".cgnk/governance/capabilities.json", {"capabilities": [capability]})
    write(project / ".cgnk/governance/path_ownership.json", {"mappings": [{"glob": "src/core.py", "capabilities": ["capability.demo.core"]}]})
    write(project / ".cgnk/governance/migrations.json", {"migrations": []})
    write(project / ".cgnk/governance/adversarial.json", {"cases": [{"id": "remove-boundary", "file": "src/core.py", "search": "BOUNDARY = True", "replace": "BOUNDARY = False", "expectedInvariant": "INV-001"}]})
    write(project / ".cgnk/governance/positive_evolution.json", {"cases": [{"id": "comment", "file": "src/core.py", "search": "BOUNDARY = True", "replace": "BOUNDARY = True  # clearer"}]})
    run(project, "git", "add", ".")
    run(project, "git", "commit", "-m", "initial")
    commit = run(project, "git", "rev-parse", "HEAD")
    write(project / ".cgnk/governance/governance.lock.json", {
        "cgnkVersion": "test", "cgnkCommit": run(TOOL_ROOT, "git", "rev-parse", "HEAD"), "verifiedProjectCommit": commit,
        "verificationVersion": "1.0.0", "verifiedAt": "2026-01-01T00:00:00Z",
        "hashes": {"invariants": {"INV-001@1": canonical_hash(invariant)}, "capabilities": {"capability.demo.core@1": canonical_hash(capability)}},
    })
    run(project, "git", "add", ".")
    run(project, "git", "commit", "-m", "add lock")
    return project


def engine(project: Path, *, strict: bool = False) -> GovernanceEngine:
    return GovernanceEngine(project, tool_root=TOOL_ROOT, strict=strict)


def test_contract_content_is_immutable_at_same_version(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    doc = json.loads((project / ".cgnk/governance/capabilities.json").read_text())
    doc["capabilities"][0]["guarantees"] = ["weakened"]
    write(project / ".cgnk/governance/capabilities.json", doc)
    result = engine(project).verify(execute=False)
    assert result["status"] == "BLOCK"
    assert result["contractDrift"][0]["code"] == "CONTRACT_IMMUTABILITY"


def test_new_contract_version_is_allowed_when_old_version_remains(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    doc = json.loads((project / ".cgnk/governance/capabilities.json").read_text())
    doc["capabilities"].append({**doc["capabilities"][0], "version": 2, "description": "Evolution"})
    write(project / ".cgnk/governance/capabilities.json", doc)
    write(project / ".cgnk/governance/migrations.json", {"migrations": [{"from": "capability.demo.core@1", "to": "capability.demo.core@2", "reason": "safe evolution", "compatibility": "backward_compatible", "affectedInvariants": ["INV-001"], "requiredVerification": ["test:boundary"]}]})
    assert engine(project).verify(execute=False)["status"] == "PASS"


def test_version_bump_requires_migration_and_weakening_still_needs_review(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    doc = json.loads((project / ".cgnk/governance/permanent_invariants.json").read_text())
    doc["invariants"].append({**doc["invariants"][0], "version": 2, "description": "weaker"})
    write(project / ".cgnk/governance/permanent_invariants.json", doc)
    assert any(check["code"] == "CONTRACT_MIGRATION_MISSING" for check in engine(project).verify(execute=False)["checks"])
    write(project / ".cgnk/governance/migrations.json", {"migrations": [{"from": "INV-001@1", "to": "INV-001@2", "reason": "requested weakening", "compatibility": "weakening", "affectedInvariants": ["INV-001"], "requiredVerification": ["test:boundary"]}]})
    assert engine(project).verify(execute=False)["status"] == "NEEDS_USER_REVIEW"


def test_constitutional_removal_needs_user_review(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    write(project / ".cgnk/governance/permanent_invariants.json", {"invariants": []})
    result = engine(project).verify(execute=False)
    assert result["status"] == "NEEDS_USER_REVIEW"
    assert result["contractDrift"][0]["code"] == "CONSTITUTIONAL_CHANGE"


def test_path_mapping_and_upward_dependency_propagation(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    doc = json.loads((project / ".cgnk/governance/capabilities.json").read_text())
    doc["capabilities"].append({"id": "capability.demo.parent", "version": 1, "title": "Parent", "description": "Parent", "guarantees": [], "dependsOn": ["capability.demo.core"], "verification": []})
    write(project / ".cgnk/governance/capabilities.json", doc)
    (project / "src/core.py").write_text("BOUNDARY = True\nCHANGE = True\n")
    result = engine(project).verify(execute=False)
    assert result["affectedCapabilities"] == ["capability.demo.core", "capability.demo.parent"]


def test_unmapped_governed_file_blocks(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    (project / "src/new.py").write_text("NEW = True\n")
    result = engine(project).verify(execute=False)
    assert result["status"] == "BLOCK"
    assert any(check["code"] == "UNGOVERNED_ARCHITECTURE_CHANGE" for check in result["checks"])


def test_missing_target_and_zero_tests_never_pass(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    (project / "tests/test_boundary.py").unlink()
    (project / "src/core.py").write_text("BOUNDARY = True\nCHANGE = True\n")
    missing = engine(project).verify()
    assert any(check["code"] == "TEST_TARGET_MISSING" for check in missing["checks"])
    (project / "tests/test_boundary.py").write_text("# no tests\n", encoding="utf-8")
    zero = engine(project).verify()
    assert any(check["code"] in {"VERIFICATION_FAILED", "ZERO_TESTS_COLLECTED"} for check in zero["checks"])


def test_unknown_checker_is_not_accepted(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    doc = json.loads((project / ".cgnk/governance/manifest.json").read_text())
    doc["verificationTargets"]["test:boundary"]["type"] = "wishful_thinking"
    write(project / ".cgnk/governance/manifest.json", doc)
    with pytest.raises(GovernanceError, match="test:boundary") as caught:
        engine(project)
    assert caught.value.status == "UNKNOWN"


def test_lock_and_tool_version_mismatch(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    lock = json.loads((project / ".cgnk/governance/governance.lock.json").read_text())
    lock["cgnkCommit"] = "0" * 40
    write(project / ".cgnk/governance/governance.lock.json", lock)
    assert engine(project).verify(execute=False)["status"] == "PASS"
    strict = engine(project, strict=True).verify(execute=False, skip_adversarial=True, skip_positive=True)
    assert strict["status"] == "BLOCK"
    assert any(check["code"] == "BLOCK_TOOL_VERSION_MISMATCH" for check in strict["checks"])


def test_record_requires_clean_tree_and_strict_pass(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    (project / "src/core.py").write_text("dirty\n")
    with pytest.raises(GovernanceError) as caught:
        engine(project, strict=True).record()
    assert caught.value.code == "RECORD_REQUIRES_CLEAN_WORKTREE"


def test_explain_is_read_only(tmp_path: Path) -> None:
    project = fixture(tmp_path)
    before = (project / ".cgnk/governance/governance.lock.json").read_bytes()
    engine(project).verify(execute=False)
    assert (project / ".cgnk/governance/governance.lock.json").read_bytes() == before
