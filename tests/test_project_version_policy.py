from scripts import project_version_policy as policy


def test_simple_project_receives_one_version_truth() -> None:
    files = policy.apply_minimum_version_governance([{"path": "README.md", "content": "# App\n"}])
    versions = [item for item in files if item["path"] == "VERSION"]
    assert versions == [{"path": "VERSION", "content": "0.1.0\n"}]
    assert policy.apply_minimum_version_governance(files) == files


def test_json_to_sqlite_upgrade_supersedes_writer_and_keeps_reader_only() -> None:
    result = policy.validate_upgrade(
        active_implementations=[
            {
                "id": "sqlite-store",
                "responsibility": "persistence",
                "state": "ACTIVE",
                "supersedes": ["json-store"],
            }
        ],
        compatibility_items=[
            {
                "id": "json-importer",
                "state": "COMPAT_ONLY",
                "remove_in": "0.4.0",
                "allowed_operations": ["read", "migrate"],
            }
        ],
    )
    assert result["status"] == "PASS"
    assert result["superseded"] == ["json-store"]


def test_upgrade_rejects_parallel_active_writer_and_compat_writer() -> None:
    result = policy.validate_upgrade(
        active_implementations=[
            {"id": "json-store", "responsibility": "persistence", "state": "ACTIVE", "supersedes": []},
            {"id": "sqlite-store", "responsibility": "persistence", "state": "ACTIVE", "supersedes": ["json-store"]},
        ],
        compatibility_items=[
            {"id": "json-importer", "state": "COMPAT_ONLY", "remove_in": "0.4.0", "allowed_operations": ["write"]}
        ],
    )
    assert result["status"] == "NEEDS_REWORK"
    assert "duplicate_active_authority:persistence" in result["failures"]
    assert "compatibility_writer_forbidden:json-importer" in result["failures"]
