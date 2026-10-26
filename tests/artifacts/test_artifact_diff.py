from __future__ import annotations

import json

import pytest

from cgkn.artifacts import artifact_diff


pytestmark = [pytest.mark.happy_path, pytest.mark.boundary, pytest.mark.determinism]


def test_no_change_and_mapping_reorder_are_semantically_equal() -> None:
    assert artifact_diff({"a": 1, "b": {"x": 2}}, {"b": {"x": 2}, "a": 1}) == {"added": [], "removed": [], "changed": []}


def test_nested_mapping_list_and_type_changes_are_stable() -> None:
    old = {"nested": {"remove": 1, "change": [1, 2]}, "type": 1}
    new = {"nested": {"add": 2, "change": [1, 3, 4]}, "type": "1"}
    result = artifact_diff(old, new)
    assert [item["path"] for item in result["added"]] == ["/nested/add", "/nested/change/2"]
    assert [item["path"] for item in result["removed"]] == ["/nested/remove"]
    assert [item["path"] for item in result["changed"]] == ["/nested/change/1", "/type"]
    assert json.dumps(result, sort_keys=True) == json.dumps(artifact_diff(old, new), sort_keys=True)


def test_list_tail_removal_is_reported() -> None:
    result = artifact_diff({"items": [1, 2, 3]}, {"items": [1]})
    assert [item["path"] for item in result["removed"]] == ["/items/1", "/items/2"]


@pytest.mark.negative
def test_invalid_non_json_input_is_rejected_and_inputs_are_not_mutated() -> None:
    old = {"items": [1]}; new = {"items": [2]}
    result = artifact_diff(old, new)
    result["changed"][0]["old"] = "mutated"
    assert old == {"items": [1]} and new == {"items": [2]}
    with pytest.raises(TypeError):
        artifact_diff({"bad": {1}}, {})
    with pytest.raises(ValueError):
        artifact_diff({"bad": float("nan")}, {})
