import pytest

from cgkn.application.software_project.catalog import list_cases


@pytest.mark.boundary
@pytest.mark.generation
def test_real_generation_contract_has_required_entrypoints_and_public_acceptance():
    for case in list_cases():
        assert case.entrypoint and case.public_goal and case.public_acceptance
        assert "hidden" not in case.public_goal.lower()
        assert all("hidden" not in item.lower() for item in case.public_acceptance)
