from __future__ import annotations

import importlib.util
import pathlib

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.e2e]


ROOT = pathlib.Path(__file__).resolve().parents[1]
EVAL = ROOT / "generated" / "front_back_separate_eval" / "run_front_back_eval.py"


def _load_eval_module():
    spec = importlib.util.spec_from_file_location("front_back_eval", EVAL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backend_large_project_generation_controlled_fixture_eval() -> None:
    module = _load_eval_module()
    result = module.run_backend_controlled_eval()

    assert result["provider_mode"] == "controlled_fixture"
    assert result["classification"] == "generated_but_missing_delivery_package"
    assert result["architecture_contract_verdict"] == "PASS"
    assert result["runnable_contract_verdict"] == "PASS"
    assert result["real_test_execution_verdict"] == "PASS"
    assert result["visual_evidence_verdict"] == "FAIL"
    assert result["public_delivery_gate_verdict"] in {"PASS", "FAIL"}
    assert result["generated_file_count"] >= 20
    assert result["frontend_file_count"] >= 6
    assert result["backend_file_count"] >= 6
    assert module.real_provider_not_run()["verdict"] == "NOT_PROVEN"
