from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import final_delivery_truth
import formal_model_contract


def test_uses_model_false_fails_formal_gate(tmp_path: pathlib.Path) -> None:
    formal_model_contract.append_model_call(
        tmp_path,
        stage="planning",
        provider="local_model_router",
        model="qwen2.5:7b-instruct",
        requested=True,
        executed=True,
        status="ok",
        used_in_formal_chain=True,
        input_value="plan",
        output_value="ok",
    )

    result = formal_model_contract.evaluate_model_participation(
        context="feasibility_live_smoke",
        run_dir=tmp_path,
        usage_plan={"requires_model": True, "uses_model": False},
    )

    assert result["status"] == "fail"
    assert result["reason"] == formal_model_contract.FORMAL_MODEL_NOT_USED


def test_external_smoke_ok_but_missing_formal_ledger_fails(tmp_path: pathlib.Path) -> None:
    result = formal_model_contract.evaluate_model_participation(
        context="commercial_readiness",
        run_dir=tmp_path,
        usage_plan={"requires_model": True, "uses_model": True},
    )

    assert result["status"] == "fail"
    assert result["reason"] == formal_model_contract.FORMAL_MODEL_EVIDENCE_MISSING


def test_fallback_ok_without_delivery_evidence_cannot_pass_final_delivery(tmp_path: pathlib.Path) -> None:
    project_dir = tmp_path / "candidate"
    project_dir.mkdir()
    formal_model_contract.append_model_call(
        tmp_path,
        stage="repair",
        provider="local_model_router",
        model="qwen2.5:7b-instruct",
        requested=True,
        executed=True,
        status="ok",
        used_in_formal_chain=True,
        input_value="repair",
        output_value="ok",
    )

    result = final_delivery_truth.evaluate(
        project_dir,
        {},
        {"goal": "demo", "run_dir": str(tmp_path)},
        evidence={"run_dir": str(tmp_path), "usage_plan": {"requires_model": True, "uses_model": True}},
        phase="final",
    )

    assert result["status"] == "fail"
    assert result["metadata"]["formal_model_gate"]["status"] == "pass"
    assert result["metadata"]["delivery_allowed"] is False
