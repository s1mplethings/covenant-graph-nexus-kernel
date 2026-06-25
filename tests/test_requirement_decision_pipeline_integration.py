from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import run_local_pipeline
from scripts import run_local_pipeline_impl


def test_provider_component_payload_contains_requirement_decision_context() -> None:
    plan_doc = {
        "selected_requirement": {"selected_requirement_id": "req_1"},
        "mvp_scope": {"text": "must do local workflow"},
        "non_goals": {"text": "no cloud-only mode"},
        "acceptance_contract": {"contract_id": "requirement_acceptance_contract_v1"},
    }
    payload = run_local_pipeline_impl.provider_component_payload(
        goal="Build a local workbench",
        component={"id": "frontend"},
        component_pipeline={"components": [{"id": "frontend"}]},
        plan_doc=plan_doc,
        blueprint={},
        online_inputs={},
        market_research={},
        prior_manifest=[],
        repair_errors=[],
    )

    assert payload["selected_requirement"]["selected_requirement_id"] == "req_1"
    assert payload["mvp_scope"]["text"] == "must do local workflow"
    assert payload["non_goals"]["text"] == "no cloud-only mode"
    assert payload["acceptance_contract"]["contract_id"] == "requirement_acceptance_contract_v1"


def test_run_local_pipeline_no_api_writes_requirement_decision_before_implementation() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        result = run_local_pipeline.execute(
            argparse.Namespace(
                plan="",
                goal="我想做一个本地资料整理和研究工作台",
                out_dir=str(root / "project"),
                run_dir=str(root / "run"),
                resume_run_dir="",
                result=str(root / "result.json"),
                allow_network=False,
                allow_provider=False,
                use_api=False,
                model="gpt-test",
                small_model="",
                large_model="",
                disable_model_routing=True,
                video=None,
                timeout=60,
                provider_semantic_repair_attempts=None,
                post_build_repair_attempts=None,
                allow_model_usage_planning=False,
                phase_log_path="",
            )
        )

        req_dir = root / "run" / "requirement_decision"
        selected = json.loads((req_dir / "selected_requirement.json").read_text(encoding="utf-8"))
        assert result["status"] == "BLOCKED"
        assert result["reason"] == "provider_api_disabled_by_default"
        assert "requirement_decision" in result
        assert selected["selected_requirement_id"]
        assert (req_dir / "acceptance_contract.json").exists()
