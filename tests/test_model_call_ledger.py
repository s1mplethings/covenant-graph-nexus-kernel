from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import formal_model_contract


def test_ledger_only_external_smoke_is_not_formal_evidence(tmp_path: pathlib.Path) -> None:
    formal_model_contract.append_model_call(
        tmp_path,
        stage="external_smoke",
        provider="api_agent",
        model="gpt-5.4-nano",
        requested=True,
        executed=True,
        status="ok",
        used_in_formal_chain=False,
        input_value="ping",
        output_value="pong",
    )

    result = formal_model_contract.evaluate_model_participation(
        context="formal_live_generation",
        run_dir=tmp_path,
        usage_plan={"requires_model": True, "uses_model": True},
    )

    assert result["status"] == "fail"
    assert result["reason"] == formal_model_contract.FORMAL_MODEL_LEDGER_EXTERNAL_ONLY


def test_formal_planning_record_counts_as_model_participation(tmp_path: pathlib.Path) -> None:
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
        output_value={"route": "formal"},
    )

    result = formal_model_contract.evaluate_model_participation(
        context="formal_live_generation",
        run_dir=tmp_path,
        usage_plan={"requires_model": True, "uses_model": True},
    )

    assert result["status"] == "pass"
    assert result["formal_model_evidence"] is True
    assert result["formal_records"] == 1
