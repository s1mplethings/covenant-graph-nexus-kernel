import pytest

from cgkn.application.software_project.catalog import get_case, list_cases


@pytest.mark.happy_path
@pytest.mark.boundary
def test_public_catalog_contains_three_greenfield_types_and_repair():
    assert {item.case_id for item in list_cases()} == {"cli_csv_cleaner", "local_json_notes", "local_web_notes", "multi_module_job_api", "seeded_repair"}
    assert get_case("local_web_notes").runtime_command[:3] == ("python", "-m", "notes_app")


@pytest.mark.negative
def test_unknown_case_is_rejected():
    with pytest.raises(ValueError, match="unknown"):
        get_case("hidden")
