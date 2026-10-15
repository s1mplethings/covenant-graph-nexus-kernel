from __future__ import annotations

import importlib.util
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "autonomous_validation_pass3", ROOT / "scripts" / "autonomous_validation_pass3.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_public_context_uses_goals_and_excludes_tests_and_oracles() -> None:
    context = module.public_context(ROOT, module.PROJECTS[0])
    serialized = json.dumps(context, ensure_ascii=False).lower()

    assert context["generated_by_cgkn"] is True
    assert context["operation_contract"]
    assert all(not item["path"].lower().startswith("tests/") for item in context["materials"])
    assert "independent_oracle" not in serialized
    assert "validation_report.json" not in serialized


def test_action_contract_rejects_model_invented_operations() -> None:
    spec = next(item for item in module.PROJECTS if item.project_id == "orbit360")
    plan = module.validate_plan(
        spec,
        {
            "actions": [
                {"op": "plan", "args": {"units": 12, "width": 4}},
                {"op": "arbitrary_shell", "args": {"command": "whoami"}},
            ]
        },
        6,
    )

    assert [item["op"] for item in plan["actions"]] == ["plan"]
    assert plan["rejected_actions"][0]["index"] == 1


def test_report_oracle_detects_content_free_report() -> None:
    row = {
        "observation_id": "obs-04",
        "op": "build_report",
        "args": {"documents": "all_import_results", "tasks": []},
        "result": {"document_count": 1, "task_count": 0, "sections": ["summary"]},
        "operation_inputs": {"documents": [{"title": "Mars", "content": "red planet"}], "tasks": []},
        "before": {"documents": [], "storage_tasks": [], "service_tasks": []},
        "after": {"documents": [], "storage_tasks": [], "service_tasks": []},
        "returncode": 0,
    }

    issues = module.knowledge_oracle(row)

    assert [item["issue_type"] for item in issues] == ["report_omits_source_content"]
    assert issues[0]["oracle_kind"] == "deterministic"


def test_feedback_adjustment_requires_later_actions_to_cite_observations() -> None:
    result = module.adjustment_audit(
        [
            {
                "project_id": "sample",
                "plans": [
                    {"round": 1, "actions": [{"adapts_from": []}]},
                    {"round": 2, "actions": [{"adapts_from": ["obs-01"]}]},
                    {"round": 3, "actions": [{"adapts_from": ["obs-02"]}]},
                ],
            }
        ]
    )

    assert result["all_projects_adjusted"] is True
    assert result["projects"][0]["feedback_citing_actions"] == 2
    assert result["projects"][0]["invalid_feedback_citations"] == []


def test_cost_conclusion_does_not_overclaim_multi_round_value() -> None:
    finding = {"finding_key": "project:issue", "independently_confirmed": True}
    groups = {
        "A": {"findings": [finding], "estimated_cost_usd": 0.001},
        "C": {"findings": [], "estimated_cost_usd": 0},
        "D": {"findings": [finding], "estimated_cost_usd": 0.002},
    }

    answers, recommendation = module.derive_research_conclusion(
        groups, ["project:issue"], {"all_projects_adjusted": True}
    )

    assert "No evidence" in answers["model_cost_worth_it"]
    assert "did not outperform A" in recommendation


def test_pass3_report_schema_preserves_research_boundary() -> None:
    schema = json.loads(
        (ROOT / "schemas" / "autonomous_validation_pass3_report_v1.schema.json").read_text(encoding="utf-8")
    )

    assert schema["properties"]["formal_evidence_status"]["const"] == "NOT_EVALUATED"
    assert schema["properties"]["release_authority"]["const"] is False

