from __future__ import annotations

import copy

import pytest

from experiments.semantic_artifact_design.common.case import CLI_UNITS, case_and_units, project_contract, structure_payload
from experiments.semantic_artifact_design.common.designs import get_design


@pytest.mark.parametrize("design_id", ["A", "B", "C"])
def test_all_designs_roundtrip_hash_immutability_and_same_facts(design_id):
    adapter = get_design(design_id)
    case, units = case_and_units("cli_csv_cleaner")
    artifact = adapter.create("project.contract@1", case.case_id, project_contract(case))
    rendered = adapter.as_dict(artifact)
    loaded = adapter.load(copy.deepcopy(rendered))
    assert adapter.as_dict(loaded) == rendered
    assert rendered["content_hash"].startswith("sha256:")
    with pytest.raises(TypeError):
        loaded.payload["project_id"] = "changed"


@pytest.mark.parametrize("design_id", ["A", "B", "C"])
def test_unknown_kind_version_malformed_missing_and_extra_are_rejected(design_id):
    adapter = get_design(design_id)
    case, _ = case_and_units("cli_csv_cleaner")
    payload = project_contract(case)
    with pytest.raises(ValueError): adapter.create("unknown@1", case.case_id, payload)
    artifact = adapter.create("project.contract@1", case.case_id, payload)
    value = adapter.as_dict(artifact)
    broken = dict(value); broken["schema_version"] = "2.0"
    with pytest.raises(ValueError): adapter.load(broken)
    broken = dict(value); broken["payload"] = dict(value["payload"]); broken["payload"].pop("public_goal")
    with pytest.raises(ValueError): adapter.load(broken)
    broken = dict(value); broken["payload"] = dict(value["payload"]); broken["payload"]["extra"] = True
    with pytest.raises(ValueError): adapter.load(broken)
    broken = dict(value); broken["content_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError): adapter.load(broken)


@pytest.mark.parametrize("design_id", ["A", "B", "C"])
def test_reference_graph_rejects_dangling_cycles_and_stale_state(design_id):
    adapter = get_design(design_id)
    case, units = case_and_units("cli_csv_cleaner")
    contract = adapter.create("project.contract@1", case.case_id, project_contract(case))
    structure = adapter.create("project.structure@1", case.case_id, structure_payload(units), inputs=(contract.artifact_id,))
    adapter.validate_graph((contract, structure), current_revisions={case.case_id: 1})
    dangling = adapter.create("project.structure@1", "other", structure_payload(units), inputs=("missing",))
    with pytest.raises(ValueError, match="dangling"): adapter.validate_graph((dangling,))
    stale = adapter.create("project.structure@1", case.case_id, structure_payload(units), revision=1)
    with pytest.raises(ValueError, match="stale"): adapter.validate_graph((stale,), current_revisions={case.case_id: 2})
    first = adapter.create("project.contract@1", "one", project_contract(case), inputs=("placeholder",))
    second = adapter.create("project.structure@1", "two", structure_payload(units), inputs=(first.artifact_id,))
    # Recreate first with a reference to second while preserving a valid, deterministic id is impossible through the public constructor;
    # graph cycle handling is exercised using two minimal proxies with canonical identities.
    class Proxy:
        def __init__(self, identity, inputs): self.artifact_id, self.inputs, self.subject_ref, self.revision = identity, inputs, identity, 1
    with pytest.raises(ValueError, match="cyclic"): adapter.validate_graph((Proxy("a", ("b",)), Proxy("b", ("a",))))


def test_designs_expose_equal_semantic_kind_coverage_with_distinct_complexity():
    assert get_design("A").complexity() == {"core_types": 11, "schema_count": 10}
    assert get_design("B").complexity() == {"core_types": 2, "schema_count": 10}
    assert get_design("C").complexity() == {"core_types": 4, "schema_count": 10}
