from __future__ import annotations

import json
from pathlib import Path

from scripts.canonical_version_gate import REQUIRED_AUTHORITIES, validate_repository


def architecture(version: str = "0.3.0") -> dict:
    authorities = {name: f"owner:{name}" for name in REQUIRED_AUTHORITIES}
    authorities["clarification"] = None
    return {
        "kind": "CGKNCurrentArchitecture",
        "schema_version": "1.0",
        "product_version": version,
        "architecture_generation": "test",
        "supersedes": [],
        "authorities": authorities,
        "canonical_routes": {},
        "compatibility_surfaces": [],
        "forbidden_parallel_authorities": True,
    }


def deprecations(items: list[dict] | None = None) -> dict:
    return {"kind": "CGKNDeprecationRegistry", "schema_version": "1.0", "items": items or []}


def compat(item_id: str = "json-importer", *, remove_in: str = "0.4.0") -> dict:
    return {
        "id": item_id,
        "state": "COMPAT_ONLY",
        "responsibility": "read old JSON",
        "replacement": "sqlite-store",
        "deprecated_in": "0.3.0",
        "remove_in": remove_in,
        "paths": ["compat/json_importer.py"],
        "allowed_consumers": ["migration"],
        "allowed_operations": ["read", "migrate"],
        "canonical_outputs": [],
        "new_production_forbidden": True,
    }


def repo(tmp_path: Path, *, version: str = "0.3.0") -> Path:
    (tmp_path / "VERSION").write_text(version + "\n", encoding="utf-8")
    for directory in ("governance", "scripts", "cgkn", "compat", "docs"):
        (tmp_path / directory).mkdir()
    (tmp_path / "README.md").write_text("current truth\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("current truth\n", encoding="utf-8")
    for name in ("00_kernel_contract.md", "01_contract_registry.md", "15_release_versioning.md"):
        (tmp_path / "docs" / name).write_text("current truth\n", encoding="utf-8")
    return tmp_path


def codes(result: dict) -> set[str]:
    return {failure["code"] for failure in result["failures"]}


def test_repository_current_gate_passes() -> None:
    result = validate_repository(Path(__file__).resolve().parents[1])
    assert result["status"] == "PASS", result["failures"]


def test_duplicate_active_authority_fails(tmp_path: Path) -> None:
    root = repo(tmp_path)
    current = architecture()
    current["authorities"]["requirement"] = ["old_requirement_engine", "canonical_goal_spec_compiler"]
    result = validate_repository(root, architecture=current, deprecations=deprecations())
    assert result["status"] == "NEEDS_REWORK"
    assert "duplicate_active_authority" in codes(result)


def test_compatibility_cannot_produce_current_artifact(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / "compat" / "json_importer.py").write_text("def read(): pass\n", encoding="utf-8")
    item = compat()
    item["allowed_operations"].append("write")
    item["canonical_outputs"] = ["current.db"]
    result = validate_repository(root, architecture=architecture(), deprecations=deprecations([item]))
    assert "compatibility_produces_canonical_output" in codes(result)


def test_expired_compatibility_fails(tmp_path: Path) -> None:
    root = repo(tmp_path, version="0.4.0")
    (root / "compat" / "json_importer.py").write_text("def read(): pass\n", encoding="utf-8")
    result = validate_repository(root, architecture=architecture("0.4.0"), deprecations=deprecations([compat(remove_in="0.4.0")]))
    assert "expired_compatibility" in codes(result)


def test_superseded_production_import_fails(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / "scripts" / "old_impl.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "scripts" / "main.py").write_text("import scripts.old_impl\n", encoding="utf-8")
    current = architecture()
    current["implementations"] = [{"id": "old", "responsibility": "store", "state": "SUPERSEDED", "paths": ["scripts/old_impl.py"]}]
    result = validate_repository(root, architecture=current, deprecations=deprecations())
    assert "superseded_production_import" in codes(result)


def test_current_document_cannot_claim_superseded_owner(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / "README.md").write_text("old_requirement_engine is current\n", encoding="utf-8")
    current = architecture()
    current["forbidden_current_claims"] = ["old_requirement_engine is current"]
    result = validate_repository(root, architecture=current, deprecations=deprecations())
    assert "stale_current_documentation" in codes(result)


def test_old_schema_reader_is_allowed_but_writer_is_not(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / "compat" / "json_importer.py").write_text("def read(): pass\n", encoding="utf-8")
    reader = validate_repository(root, architecture=architecture(), deprecations=deprecations([compat()]))
    assert reader["status"] == "PASS", reader["failures"]
    writer = compat()
    writer["canonical_outputs"] = ["legacy-schema-v1.json"]
    result = validate_repository(root, architecture=architecture(), deprecations=deprecations([writer]))
    assert "compatibility_produces_canonical_output" in codes(result)


def test_pure_new_project_passes_without_compatibility(tmp_path: Path) -> None:
    root = repo(tmp_path)
    result = validate_repository(root, architecture=architecture(), deprecations=deprecations())
    assert result["status"] == "PASS", result["failures"]


def test_version_mismatch_fails(tmp_path: Path) -> None:
    root = repo(tmp_path)
    result = validate_repository(root, architecture=architecture("0.2.0"), deprecations=deprecations())
    assert "version_mismatch" in codes(result)


def test_removed_item_cannot_remain_in_registry(tmp_path: Path) -> None:
    root = repo(tmp_path)
    result = validate_repository(root, architecture=architecture(), deprecations=deprecations([compat()]))
    assert "removed_item_still_registered" in codes(result)


def test_json_to_sqlite_upgrade_keeps_only_import_compatibility(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / "compat" / "json_importer.py").write_text("def import_json(): pass\n", encoding="utf-8")
    current = architecture()
    current["implementations"] = [
        {"id": "sqlite-store", "responsibility": "persistence", "state": "ACTIVE", "paths": ["scripts/sqlite_store.py"], "supersedes": ["json-store"]}
    ]
    result = validate_repository(root, architecture=current, deprecations=deprecations([compat()]))
    assert result["status"] == "PASS", result["failures"]


def test_patch_accumulation_with_multiple_active_owners_fails(tmp_path: Path) -> None:
    root = repo(tmp_path)
    current = architecture()
    current["implementations"] = [
        {"id": "foo", "responsibility": "persistence", "state": "ACTIVE", "paths": ["scripts/foo.py"]},
        {"id": "foo-v2", "responsibility": "persistence", "state": "ACTIVE", "paths": ["scripts/foo_v2.py"]},
        {"id": "foo-new", "responsibility": "persistence", "state": "ACTIVE", "paths": ["scripts/foo_new.py"]},
    ]
    result = validate_repository(root, architecture=current, deprecations=deprecations())
    assert "duplicate_active_authority" in codes(result)
