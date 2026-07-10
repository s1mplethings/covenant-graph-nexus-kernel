from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.agent_long_run_evaluator import phase1_controlled_replay, phase2_real_leaf, phase4_failure_repair

pytestmark = [pytest.mark.longrun, pytest.mark.slow, pytest.mark.e2e]


def test_long_run_phase1_controlled_replay_passes(tmp_path: pathlib.Path) -> None:
    result = phase1_controlled_replay(tmp_path)

    assert result["verdict"] == "PASS"
    assert result["agent_count"] >= 20
    assert result["public_delivery_gate"] is True


def test_long_run_phase2_classifies_provider_unavailable(tmp_path: pathlib.Path) -> None:
    result = phase2_real_leaf(tmp_path, {"provider_ready": False})

    assert result["classification"] == "provider_unavailable"
    assert result["verdict"] == "BLOCKED"


def test_long_run_phase4_failure_repair_passes(tmp_path: pathlib.Path) -> None:
    result = phase4_failure_repair(tmp_path)

    assert result["verdict"] == "PASS"
    assert {item["case"] for item in result["cases"]} == {"scope_violation", "missing_file_repair", "needs_split"}
