from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
for path in (ROOT / "scripts", ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import adaptive_project_management_context  # noqa: E402
import run_local_pipeline_impl  # noqa: E402


def sample_plan() -> dict:
    return {
        "selected_requirement": {"selected_requirement_id": "req-1"},
        "acceptance_contract": {"acceptance_criteria": ["A runnable project exists."]},
        "complexity_project_contract": {},
    }


def sample_pipeline() -> dict:
    return {
        "kind": "ComponentPipelinePlan",
        "components": [
            {
                "id": "foundation",
                "label": "Foundation",
                "depends_on": [],
                "outputs": ["project structure"],
                "required_paths": ["requirements.txt"],
            },
            {
                "id": "backend",
                "label": "Backend",
                "depends_on": ["foundation"],
                "outputs": ["service contract"],
                "required_paths": ["main.py"],
            },
        ],
        "execution_order": ["foundation", "backend"],
        "merge_policy": {"required_final_files": ["README.md"]},
    }


def test_management_context_contains_value_quality_and_bounded_experience() -> None:
    context = adaptive_project_management_context.build_management_context(
        goal="Build a local API project with strong quality.",
        plan_doc=sample_plan(),
        component_pipeline=sample_pipeline(),
    )

    assert context["kind"] == "CGKNAdaptiveProjectManagementContext"
    assert context["delivery_approach"] == "hybrid"
    assert [row["id"] for row in context["component_backlog"]] == ["PB-001", "PB-002"]
    assert context["quality_management"]["definition_of_done"]
    assert len(context["enterprise_experience"]) <= 4
    assert all(
        row["experience_state"] in {"validated", "approved"}
        for row in context["enterprise_experience"]
    )
    assert "formal PASS" in context["warning"]


def test_component_projection_selects_only_current_backlog_item() -> None:
    enriched = adaptive_project_management_context.enrich_component_pipeline(
        goal="Build a local API project.",
        plan_doc=sample_plan(),
        component_pipeline=sample_pipeline(),
    )
    projection = adaptive_project_management_context.component_management_projection(enriched, "backend")

    assert projection["kind"] == "CGKNAdaptiveComponentManagementProjection"
    assert projection["selected_backlog_item"]["title"] == "Backend"
    assert len(projection["enterprise_experience"]) <= 4


def test_formal_component_pipeline_is_enriched_without_new_component_or_route() -> None:
    pipeline = run_local_pipeline_impl.component_pipeline_from_plan(
        "Build a local task board.",
        sample_plan(),
    )

    assert pipeline["adaptive_project_management"]["kind"] == "CGKNAdaptiveProjectManagementContext"
    assert [row["id"] for row in pipeline["components"]] == [
        "foundation",
        "backend",
        "frontend",
        "tests",
        "docs",
    ]
    assert "adaptive_project_management" not in pipeline["merge_policy"]


def test_provider_component_payload_uses_projection_not_full_management_context() -> None:
    enriched = adaptive_project_management_context.enrich_component_pipeline(
        goal="Build a local API project.",
        plan_doc=sample_plan(),
        component_pipeline=sample_pipeline(),
    )
    component = enriched["components"][1]
    payload = run_local_pipeline_impl.provider_component_payload(
        goal="Build a local API project.",
        component=component,
        component_pipeline=enriched,
        plan_doc=sample_plan(),
        blueprint={},
        online_inputs={},
        market_research={},
        prior_manifest=[],
        repair_errors=[],
    )

    assert "adaptive_project_management" not in payload["component_pipeline"]
    assert payload["adaptive_project_management"]["kind"] == "CGKNAdaptiveComponentManagementProjection"
    serialized = json.dumps(payload["adaptive_project_management"], ensure_ascii=False)
    assert len(serialized) < 12000
