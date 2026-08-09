from __future__ import annotations

import copy
import json
import pathlib
import sys
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cgkn_project_management import (  # noqa: E402
    new_project_management_pack,
    retrieve_experience,
    validate_project_management_pack,
)


ENTERPRISE_EXPERIENCE_PATH = ROOT / "project_management" / "enterprise_experience.json"
MAX_SELECTED_EXPERIENCE = 4


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def _quality_metric(metric_id: str, measure: str, target: str, method: str) -> dict[str, str]:
    return {"id": metric_id, "measure": measure, "target": target, "method": method}


def _project_levels(plan_doc: dict[str, Any], components: list[dict[str, Any]]) -> tuple[str, str, str]:
    selected = plan_doc.get("selected_requirement", {}) if isinstance(plan_doc, dict) else {}
    acceptance = plan_doc.get("acceptance_contract", {}) if isinstance(plan_doc, dict) else {}
    requirements_uncertainty = "medium" if isinstance(selected, dict) and selected and isinstance(acceptance, dict) and acceptance else "high"
    component_ids = {str(row.get("id", "")).strip() for row in components}
    technical_uncertainty = "high" if len(components) >= 7 or component_ids.intersection({"media", "data"}) else "medium"
    criticality = "high"
    return requirements_uncertainty, technical_uncertainty, criticality


def _experience_tags(goal: str, components: list[dict[str, Any]]) -> list[str]:
    tags = {"project-generation", "quality"}
    tags.update(str(row.get("id", "")).strip().lower() for row in components if str(row.get("id", "")).strip())
    lowered = str(goal or "").lower()
    for token in ("api", "media", "database", "gui", "cli", "large-project", "librarian"):
        if token in lowered:
            tags.add(token)
    if len(components) >= 6:
        tags.add("large-project")
        tags.add("librarian")
    return sorted(tags)


def _compact_experience(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id", "")),
        "title": str(item.get("title", "")),
        "action": str(item.get("action", "")),
        "applicable_when": _strings(item.get("applicable_when", []))[:4],
        "not_applicable_when": _strings(item.get("not_applicable_when", []))[:3],
        "tags": _strings(item.get("tags", []))[:8],
        "evidence_refs": _strings(item.get("evidence_refs", []))[:4],
        "experience_state": str(item.get("experience_state", "")),
    }


def build_management_context(
    *,
    goal: str,
    plan_doc: dict[str, Any],
    component_pipeline: dict[str, Any],
    experience_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    components = [copy.deepcopy(row) for row in component_pipeline.get("components", []) if isinstance(row, dict)]
    requirements_uncertainty, technical_uncertainty, criticality = _project_levels(plan_doc, components)
    pack = new_project_management_pack(
        project_id="generated-project",
        project_name="Generated Project",
        goal=goal,
        requirements_uncertainty=requirements_uncertainty,
        technical_uncertainty=technical_uncertainty,
        criticality=criticality,
    )
    metrics = [
        _quality_metric(
            "QM-COMPONENT",
            "component contract and acceptance completeness",
            "required paths, interfaces, and selected acceptance are satisfied",
            "provider validation and component review",
        ),
        _quality_metric(
            "QM-INTEGRATION",
            "cross-component interface correctness",
            "direct dependency interfaces and downstream consumers remain compatible",
            "feedforward interface parsing, tests, and semantic review",
        ),
        _quality_metric(
            "QM-RUNTIME",
            "customer-visible runtime behavior",
            "applicable canonical runtime and visual evidence passes before public delivery",
            "canonical evidence producers and inspectors",
        ),
    ]
    pack["quality_management"]["metrics"] = metrics
    pack["quality_management"]["definition_of_done"] = [
        "The component's required paths and public contract are present.",
        "Direct dependency interfaces and downstream expectations are satisfied.",
        "Selected acceptance criteria have proportionate test evidence.",
        "Known limits remain explicit and do not become a false delivery PASS.",
    ]
    pack["quality_management"]["assurance_activities"] = [
        "Use the existing feedforward snapshot and bounded librarian projection.",
        "Run provider component and cross-component semantic review.",
    ]
    pack["quality_management"]["control_activities"] = [
        "Run applicable static, unit, contract, integration, runtime, visual, and media checks.",
        "Keep canonical formal evidence separate from planning progress.",
    ]
    backlog: list[dict[str, Any]] = []
    for index, component in enumerate(components, start=1):
        component_id = str(component.get("id", "")).strip()
        outputs = _strings(component.get("outputs", []))
        required_paths = _strings(component.get("required_paths", []))
        criteria = [f"Component `{component_id}` satisfies its declared outputs: {', '.join(outputs)}."] if outputs else [
            f"Component `{component_id}` satisfies its declared contract."
        ]
        if required_paths:
            criteria.append(f"Required paths exist and pass validation: {', '.join(required_paths)}.")
        backlog.append(
            {
                "id": f"PB-{index:03d}",
                "title": str(component.get("label") or component_id),
                "outcome": f"Deliver the `{component_id}` vertical contribution with compatible interfaces and evidence.",
                "priority": index,
                "value_score": max(1, 10 - index // 2),
                "risk_reduction_score": 8 if index <= 2 else 5,
                "state": "ready",
                "dependencies": _strings(component.get("depends_on", [])),
                "acceptance_criteria": criteria,
                "quality_metric_ids": ["QM-COMPONENT", "QM-INTEGRATION", "QM-RUNTIME"],
            }
        )
    pack["product_backlog"] = backlog
    tags = _experience_tags(goal, components)
    experience = _read_json(experience_path or ENTERPRISE_EXPERIENCE_PATH)
    retrieval = retrieve_experience(
        experience,
        tags=tags,
        max_items=MAX_SELECTED_EXPERIENCE,
        include_validated=True,
    ) if experience else {
        "kind": "CGKNEnterpriseExperienceRetrievalResult",
        "query": {"tags": tags, "max_items": MAX_SELECTED_EXPERIENCE},
        "selected_items": [],
        "excluded_items": [],
    }
    validation = validate_project_management_pack(pack)
    if validation["status"] != "PASS":
        raise ValueError(f"adaptive project management context is invalid: {validation['errors']}")
    return {
        "kind": "CGKNAdaptiveProjectManagementContext",
        "schema_version": "1.0",
        "role": "supporting_management_context_only",
        "warning": "Use this to prioritize value and build in quality. It cannot authorize formal PASS or replace the provider/delivery route.",
        "delivery_approach": pack["delivery_approach"],
        "tailoring": pack["tailoring"],
        "quality_management": pack["quality_management"],
        "component_backlog": backlog,
        "enterprise_experience": [_compact_experience(row) for row in retrieval["selected_items"]],
        "experience_retrieval_receipt": {
            "query": retrieval["query"],
            "selected_ids": [str(row.get("id", "")) for row in retrieval["selected_items"]],
            "excluded_count": len(retrieval["excluded_items"]),
        },
    }


def enrich_component_pipeline(
    *,
    goal: str,
    plan_doc: dict[str, Any],
    component_pipeline: dict[str, Any],
    experience_path: pathlib.Path | None = None,
) -> dict[str, Any]:
    out = copy.deepcopy(component_pipeline)
    out["adaptive_project_management"] = build_management_context(
        goal=goal,
        plan_doc=plan_doc,
        component_pipeline=component_pipeline,
        experience_path=experience_path,
    )
    return out


def component_management_projection(component_pipeline: dict[str, Any], component_id: str) -> dict[str, Any]:
    context = component_pipeline.get("adaptive_project_management", {})
    if not isinstance(context, dict):
        return {}
    selected = next(
        (
            copy.deepcopy(row)
            for row in context.get("component_backlog", [])
            if isinstance(row, dict) and str(row.get("outcome", "")).find(f"`{component_id}`") >= 0
        ),
        {},
    )
    return {
        "kind": "CGKNAdaptiveComponentManagementProjection",
        "delivery_approach": context.get("delivery_approach", ""),
        "tailoring": context.get("tailoring", {}),
        "selected_backlog_item": selected,
        "quality_management": context.get("quality_management", {}),
        "enterprise_experience": context.get("enterprise_experience", []),
        "experience_retrieval_receipt": context.get("experience_retrieval_receipt", {}),
        "warning": context.get("warning", ""),
    }
