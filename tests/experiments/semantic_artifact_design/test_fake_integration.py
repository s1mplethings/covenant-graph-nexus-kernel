from __future__ import annotations

import pathlib

import pytest

from experiments.semantic_artifact_design.common.provider import ScriptedSemanticProvider
from experiments.semantic_artifact_design.common.runner import SemanticExperimentRunner


ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("design", ["A", "B", "C"])
def test_fake_greenfield_uses_cohesive_units_manifests_runtime_snapshot_and_hidden_acceptance(tmp_path, design):
    provider = ScriptedSemanticProvider()
    result = SemanticExperimentRunner(ROOT, tmp_path / "runs", client=provider).run(design, "cli_csv_cleaner")
    assert result.status == "PASS"
    assert result.receipt["worker_calls"] == 3
    assert result.receipt["tree_nodes"] == 8
    assert result.receipt["internal_pytest"] == "PASS"
    assert result.receipt["runtime"] == "PASS"
    assert result.receipt["hidden_acceptance"] == "PASS"
    assert result.receipt["snapshot_hash"].startswith("sha256:")
    assert result.receipt["manual_edits"] == 0


@pytest.mark.parametrize("design", ["A", "B", "C"])
def test_fake_seeded_repair_preserves_tree_and_reruns_only_affected_unit(tmp_path, design):
    provider = ScriptedSemanticProvider()
    result = SemanticExperimentRunner(ROOT, tmp_path / "runs", client=provider).run(design, "seeded_repair")
    assert result.status == "PASS"
    assert result.receipt["initial_test"]["status"] == "FAIL"
    assert result.receipt["repair_rounds"] == 1
    assert result.receipt["whole_replans"] == 0
    assert result.receipt["worker_calls"] == 1
    assert result.receipt["hidden_acceptance"] == "PASS"
    assert result.receipt["accepted_breaking_changes"] == 0
    assert (result.run_dir / "workspace/math_utils.py").read_text(encoding="utf-8").strip().endswith("return a + b")
