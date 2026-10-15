from __future__ import annotations

import importlib.util
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "role_driven_validation_pass2", ROOT / "scripts" / "role_driven_validation_pass2.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_public_plan_has_three_distinct_projects_and_matched_bc_tasks() -> None:
    plan = module.build_public_plan(ROOT, "a" * 40)

    assert len(plan["projects"]) == 3
    assert len({project["business_shape"] for project in plan["projects"]}) == 3
    assert plan["llm_used"] is False
    assert plan["hidden_acceptance_included"] is False
    for item in plan["tasks"]:
        assert item["B"]["role"] is not None
        assert item["C"]["role"] is None
        assert {key: value for key, value in item["B"].items() if key != "role"} == {
            key: value for key, value in item["C"].items() if key != "role"
        }


def test_public_plan_does_not_leak_hidden_defect_corpus() -> None:
    serialized = json.dumps(module.build_public_plan(ROOT, "a" * 40), sort_keys=True)

    for defect in module.HIDDEN_DEFECTS.values():
        assert defect["defect_id"] not in serialized
        assert defect["marker"] not in serialized
        assert defect["summary"] not in serialized
        assert defect["independent_oracle"] not in serialized


def test_independent_oracles_detect_each_defect_type() -> None:
    assert module.oracle_detects(
        "orbit360",
        {
            "boundary_probe_executed": True,
            "requested_delta": -1000,
            "reported_delta": -1000,
            "actual_delta": -62,
        },
    )
    assert module.oracle_detects("agent_kit", {"boundary_probe_executed": True, "canary_present": True})
    assert module.oracle_detects(
        "artifact_flow",
        {
            "boundary_probe_executed": True,
            "unaffected_snapshot_cache_hit": True,
            "changed_branch_reran": False,
        },
    )


def test_report_schema_keeps_research_result_non_authoritative() -> None:
    schema = json.loads(
        (ROOT / "schemas" / "role_driven_validation_pass2_report_v1.schema.json").read_text(encoding="utf-8")
    )

    assert schema["properties"]["formal_evidence_status"]["const"] == "NOT_EVALUATED"
    assert schema["properties"]["release_authority"]["const"] is False
    assert schema["properties"]["llm_used"]["const"] is False

