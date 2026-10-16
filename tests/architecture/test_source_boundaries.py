from __future__ import annotations

import pathlib
import sys

import pytest


SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import receipt_freshness
import source_boundaries


def test_boundaries_classify_only_their_owned_source() -> None:
    assert source_boundaries.BOUNDARIES["kernel"].contains("cgkn/runtime/dag_runner.py")
    assert not source_boundaries.BOUNDARIES["kernel"].contains("cgkn/application/software_project/service.py")
    assert source_boundaries.BOUNDARIES["application"].contains("tests/application/software_project/test_bundle.py")
    assert source_boundaries.BOUNDARIES["experiment"].contains("experiments/semantic_artifact_design/common/runner.py")
    assert not source_boundaries.BOUNDARIES["experiment"].contains("experiments/semantic_artifact_design/receipts/repeat.json")


def test_boundary_identity_is_stable_and_unknown_boundary_fails() -> None:
    assert source_boundaries.boundary_identity("kernel") == source_boundaries.boundary_identity("kernel")
    with pytest.raises(ValueError, match="unknown source boundary"):
        source_boundaries.boundary_identity("unknown")


def test_current_receipts_are_fresh_in_their_own_boundaries() -> None:
    value = receipt_freshness.check_all()
    assert value["status"] == "PASS", value
    assert {item["boundary"] for item in value["results"]} == {"kernel", "application", "experiment"}
