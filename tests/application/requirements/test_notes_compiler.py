from cgkn.application.requirements import compile_local_json_notes, compile_notes_work_units


def test_notes_compiler_is_deterministic_complete_and_hidden_bound() -> None:
    first, second = compile_local_json_notes(), compile_local_json_notes()
    assert first.obligations.as_dict() == second.obligations.as_dict()
    assert len(first.obligations.obligations) == 17
    assert first.preflight.as_dict()["status"] == "COMPLETE"
    hidden = first.preflight.as_dict()["hidden_coverage"]
    assert hidden["coverage"] == 1.0
    assert len(hidden["bound_obligation_ids"]) == 17


def test_notes_work_units_separate_core_cli_and_docs_without_implementation_dependency() -> None:
    units = compile_notes_work_units(compile_local_json_notes())
    assert [unit.work_unit_id for unit in units] == ["WU-CORE", "WU-CLI", "WU-DOCS"]
    core, cli, docs = units
    assert set(core.target_paths) == {"notes/__init__.py", "notes/model.py", "notes/store.py", "notes/service.py"}
    assert cli.target_paths == ("notes/__main__.py",) and not cli.depends_on and not cli.allowed_read_paths
    assert docs.target_paths == ("README.md",) and not docs.depends_on and not docs.allowed_read_paths
    assert "INTERFACE-NOTES-CLI-001" in cli.interface_contract_refs

