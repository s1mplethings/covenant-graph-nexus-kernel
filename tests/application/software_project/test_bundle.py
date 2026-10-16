import pytest

from cgkn.application.software_project.bundle import CAPABILITY_EXECUTORS, SoftwareProjectBundle


@pytest.mark.happy_path
@pytest.mark.boundary
def test_bundle_exposes_required_components_without_pipeline_order():
    bundle = SoftwareProjectBundle.build()
    assert set(CAPABILITY_EXECUTORS) == bundle.known_capabilities
    assert len(bundle.components) == len(bundle.capabilities) == 9
    assert all(item.lifecycle_status.value == "ADMITTED" for item in bundle.capabilities)
    assert not any("stage" in key.lower() for row in bundle.catalog.values() for key in row)
