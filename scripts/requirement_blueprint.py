#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import pathlib
import re
import sys
from datetime import datetime, timezone
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import local_intent_router


ROOT = pathlib.Path(__file__).resolve().parents[1]

AGENT_SEQUENCE = [
    "RequirementAgent",
    "IOContractAgent",
    "GapAgent",
    "FeatureAgent",
    "CapabilityAgent",
    "TechSearchAgent",
    "TechDecisionAgent",
    "BlueprintAgent",
    "TaskAgent",
    "ReviewAgent",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    write_text(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(term in lowered for term in terms)


def source_value(value: Any, source_type: str, confidence: float) -> dict[str, Any]:
    return {"value": value, "source_type": source_type, "confidence": round(confidence, 2)}


def answer_map(answers: list[dict[str, str]] | None) -> dict[str, str]:
    return {str(row.get("field", "")): str(row.get("answer", "")) for row in answers or []}


def infer_project_type(requirement: str) -> str:
    routed = local_intent_router.classify_project_type(requirement)
    if routed.get("project_type") != "unknown_project_type":
        return str(routed["project_type"])
    if contains_any(requirement, ("blueprint generator", "requirement blueprint generator", "需求蓝图生成器")):
        return "requirement_blueprint_generator"
    if contains_any(requirement, ("refactor", "migration", "rewrite", "重构", "迁移")):
        return "project_refactor"
    if contains_any(requirement, ("test", "verify", "validate", "测试", "验证", "验收")):
        return "project_test_pipeline"
    if contains_any(requirement, ("dashboard", "report", "报表", "报告", "统计")):
        return "reporting_application"
    return "unknown_project_type"


def infer_target_users(requirement: str, answers: dict[str, str]) -> list[str]:
    explicit = answers.get("target_user", "").strip()
    if explicit:
        return [explicit]
    if contains_any(requirement, ("developer", "engineer", "api", "code", "开发", "工程", "代码")):
        return ["developer_or_technical_lead"]
    if contains_any(requirement, ("operator", "ops", "admin", "运营", "管理员")):
        return ["operator_or_admin"]
    return ["project_owner", "developer"]


def build_requirement_spec(requirement: str, answers: dict[str, str]) -> dict[str, Any]:
    intent = local_intent_router.classify_project_type(requirement)
    project_type = str(intent.get("project_type") or infer_project_type(requirement))
    target_users = infer_target_users(requirement, answers)
    boundary = answers.get("scope_boundary", "").strip()
    return {
        "project_type": source_value(project_type, str(intent.get("intent_source", "raw_user_message")), float(intent.get("confidence", 0.72))),
        "domain": source_value(str(intent.get("domain", "unknown")), str(intent.get("intent_source", "raw_user_message")), float(intent.get("confidence", 0.72))),
        "required_features": source_value(intent.get("required_features", []), str(intent.get("intent_source", "raw_user_message")), float(intent.get("confidence", 0.72))),
        "non_goals": source_value(intent.get("non_goals", []), str(intent.get("intent_source", "raw_user_message")), float(intent.get("confidence", 0.72))),
        "business_goal": source_value(clean_text(intent.get("raw_user_message") or requirement) or "User request needs explicit clarification before project generation.", "explicit", 0.95),
        "target_users": source_value(target_users, "explicit" if answers.get("target_user") else "inferred", 0.76),
        "scenarios": [
            source_value("User submits a natural-language project request.", "explicit", 0.9),
            source_value("System extracts requirements, inputs, outputs, gaps, features, capabilities, and tasks.", "assumed", 0.78),
            source_value("Developer reviews generated blueprint artifacts before implementation.", "assumed", 0.74),
        ],
        "pain_points": [
            source_value("Initial requirements are often underspecified.", "inferred", 0.82),
            source_value("Implementation tasks need traceability to accepted inputs, outputs, and acceptance criteria.", "assumed", 0.84),
            source_value("Technology choices should be tied to capabilities instead of broad labels.", "assumed", 0.8),
        ],
        "scope_boundary": [
            source_value(
                boundary or "Generate traceable blueprint artifacts and continue through the CGNK project-generation flow.",
                "explicit" if boundary else "assumed",
                0.72,
            )
        ],
    }


def build_io_contract(requirement: str, requirement_spec: dict[str, Any], answers: dict[str, str]) -> dict[str, Any]:
    wants_docs = contains_any(requirement, ("word", "pdf", "excel", "doc", "csv", "file", "upload", "文档", "上传", "文件"))
    wants_export = contains_any(requirement, ("export", "download", "导出", "下载", "交付"))
    storage_answer = answers.get("data_storage", "").strip()
    return {
        "input_contract": {
            "input_sources": [
                source_value("Natural-language requirement entered by the user.", "explicit", 0.96),
                source_value("Optional supporting files or documents.", "inferred" if wants_docs else "unknown", 0.64 if wants_docs else 0.35),
            ],
            "input_types": ["plain_text", "document"] if wants_docs else ["plain_text"],
            "required_fields": ["project_goal", "requirement_description"],
            "optional_fields": ["target_user", "tech_preference", "acceptance_criteria", "existing_documents"],
            "unknowns": [] if wants_docs else ["Whether supporting files are required."],
        },
        "process_contract": {
            "main_process": "Convert raw user intent into traceable engineering blueprint artifacts.",
            "steps": AGENT_SEQUENCE,
            "state_transitions": [
                "created",
                "requirement_submitted",
                "requirement_analyzed",
                "io_analyzed",
                "gap_checked",
                "features_generated",
                "capabilities_mapped",
                "tech_decided",
                "blueprint_generated",
                "tasks_generated",
                "reviewed",
            ],
        },
        "output_contract": {
            "output_types": [
                "requirement_spec",
                "io_contract",
                "feature_spec",
                "capability_map",
                "tech_candidates",
                "tech_decisions",
                "architecture_diagram",
                "api_spec",
                "db_schema",
                "frontend_pages",
                "task_backlog",
                "prd",
            ],
            "output_formats": ["json", "markdown", "mermaid", "openapi_yaml", "sql", "csv"],
            "consumers": requirement_spec.get("target_users", {}).get("value", ["developer", "project_manager"]),
            "storage": source_value(
                storage_answer or "Persist runtime artifacts as local JSON, Markdown, Mermaid, YAML, SQL, and CSV files unless the requirement asks for another store.",
                "explicit" if storage_answer else "assumed",
                0.74,
            ),
            "unknowns": [] if wants_export else ["Whether packaged export formats are required beyond local artifacts."],
        },
    }


def build_gap_analysis(requirement: str, answers: dict[str, str], assume_defaults: bool) -> dict[str, Any]:
    checks = [
        {
            "field": "target_user",
            "question": "Who will use the generated project?",
            "severity": "Level 2",
            "impact": "Shapes UX, terminology, permissions, and acceptance criteria.",
            "default_assumption": "Project owner and developer.",
        },
        {
            "field": "core_features",
            "question": "What are the must-have behaviors?",
            "severity": "Level 3",
            "impact": "Defines feature decomposition and generated modules.",
            "default_assumption": "Use the explicit verbs and objects in the request as must-have scope.",
        },
        {
            "field": "data_storage",
            "question": "Where should project data or artifacts be stored?",
            "severity": "Level 2",
            "impact": "Affects persistence, deployment, and test fixtures.",
            "default_assumption": "Local artifact files and browser/local runtime state.",
        },
        {
            "field": "acceptance_criteria",
            "question": "How should success be verified?",
            "severity": "Level 3",
            "impact": "Controls test graph and effect report.",
            "default_assumption": "Generated files exist, artifacts validate, and declared behavior has smoke checks.",
        },
    ]
    gap_items: list[dict[str, Any]] = []
    for item in checks:
        answered = bool(answers.get(item["field"], "").strip())
        resolved_by_text = item["field"] == "core_features" and len(clean_text(requirement)) >= 12
        status = "resolved" if answered or resolved_by_text or assume_defaults else "open"
        gap_items.append({**item, "status": status})
    return {"gap_items": gap_items, "can_continue": all(row["status"] == "resolved" or row["severity"] != "Level 3" for row in gap_items)}


def build_feature_spec(requirement: str, answers: dict[str, str]) -> dict[str, Any]:
    core_answer = answers.get("core_features", "").strip()
    intent = local_intent_router.classify_project_type(requirement)
    features = [
        ("Project intake", "Capture the user's project goal and supporting assumptions.", ["plain_text"], ["goal"]),
        ("Requirement understanding", "Extract business goal, users, scenarios, pain points, and boundaries.", ["goal"], ["requirement_spec"]),
        ("Input/output contract analysis", "Model input sources, processing steps, outputs, storage, and unknowns.", ["requirement_spec"], ["io_contract"]),
        ("Gap confirmation", "Classify unknowns and block only unresolved high-severity gaps.", ["requirement_spec", "io_contract"], ["gap_analysis"]),
        ("Feature decomposition", "Convert accepted requirements into buildable features.", ["requirement_spec", "io_contract"], ["feature_spec"]),
        ("Capability mapping", "Map features to implementation capabilities.", ["feature_spec"], ["capability_map"]),
        ("Technology decision", "Choose technology options from capabilities and constraints.", ["capability_map"], ["tech_decisions"]),
        ("Blueprint generation", "Emit architecture, API, database, frontend, PRD, and task artifacts.", ["tech_decisions"], ["requirement_blueprint"]),
        ("Review report", "Summarize readiness, assumptions, and risks.", ["requirement_blueprint"], ["review_report"]),
    ]
    if core_answer:
        features.insert(1, ("Explicit scope", core_answer, ["goal"], ["scope_boundary"]))
    for feature_id in reversed([str(item) for item in intent.get("required_features", []) if str(item).strip()]):
        readable_name = feature_id.replace("_", " ").title()
        features.insert(
            1,
            (
                readable_name,
                f"Implement explicitly requested capability: {feature_id}.",
                ["goal"],
                [feature_id],
            ),
        )
    return {
        "features": [
            {
                "id": f"F{index:03d}",
                "name": name,
                "description": description,
                "priority": "Must" if index <= 8 else "Should",
                "inputs": inputs,
                "outputs": outputs,
                "source_type": "explicit" if name == "Explicit scope" else "assumed",
            }
            for index, (name, description, inputs, outputs) in enumerate(features, 1)
        ]
    }


CAPABILITY_RULES = {
    "Project intake": ["text_input", "project_state", "local_artifact_storage"],
    "Explicit scope": ["scope_traceability", "assumption_capture"],
    "Requirement understanding": ["business_analysis", "source_attribution", "confidence_scoring"],
    "Input/output contract analysis": ["io_contract_modeling", "state_transition_modeling", "source_attribution"],
    "Gap confirmation": ["gap_severity_rules", "default_assumption_policy", "user_confirmation_gate"],
    "Feature decomposition": ["feature_modeling", "module_boundary_detection"],
    "Capability mapping": ["capability_taxonomy", "module_catalog_lookup"],
    "Technology decision": ["technology_scoring", "constraint_matching"],
    "Blueprint generation": ["artifact_generation", "diagram_generation", "task_generation"],
    "Review report": ["quality_review", "risk_summary"],
}


def build_capability_map(feature_spec: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for feature in feature_spec.get("features", []):
        name = str(feature.get("name", ""))
        rows.append(
            {
                "feature_id": feature.get("id"),
                "feature": name,
                "capabilities": CAPABILITY_RULES.get(name, ["custom_implementation"]),
                "trace": {"inputs": feature.get("inputs", []), "outputs": feature.get("outputs", [])},
            }
        )
    return {"capability_map": rows}


def build_tech_candidates(capability_map: dict[str, Any]) -> dict[str, Any]:
    catalog = {
        "text_input": [("browser_or_cli_text_input", "custom", "Accept requirement text")],
        "project_state": [("local JSON state", "custom", "Track generation state")],
        "local_artifact_storage": [("pathlib/json", "python", "Write reproducible local artifacts")],
        "business_analysis": [("CGNK rules", "custom", "Extract user, goal, scenario, and boundary")],
        "source_attribution": [("CGNK source model", "custom", "Keep explicit/inferred/assumed provenance")],
        "confidence_scoring": [("CGNK confidence scores", "custom", "Attach confidence values to inferred fields")],
        "io_contract_modeling": [("CGNK contract model", "custom", "Represent input/process/output contracts")],
        "state_transition_modeling": [("CGNK state model", "custom", "Track lifecycle states")],
        "gap_severity_rules": [("CGNK gap rules", "custom", "Separate blocking from non-blocking unknowns")],
        "default_assumption_policy": [("CGNK defaults", "custom", "Continue with visible assumptions when allowed")],
        "user_confirmation_gate": [("confirmation gate", "custom", "Pause when a Level 3 gap is unresolved")],
        "feature_modeling": [("feature decomposition rules", "custom", "Create feature modules")],
        "module_boundary_detection": [("module boundary rules", "custom", "Keep modules independently testable")],
        "capability_taxonomy": [("capability catalog", "custom", "Map feature to capability terms")],
        "module_catalog_lookup": [("local module catalog", "custom", "Find available contracts")],
        "technology_scoring": [("weighted decision matrix", "custom", "Score candidates by capability fit")],
        "constraint_matching": [("policy constraints", "custom", "Match effects, network, provider, and storage constraints")],
        "artifact_generation": [("CGNK artifact emitters", "custom", "Generate JSON/Markdown/YAML/SQL/CSV artifacts")],
        "diagram_generation": [("Mermaid", "spec", "Generate architecture diagrams")],
        "task_generation": [("CSV backlog", "custom", "Generate implementation tasks")],
        "quality_review": [("CGNK review checks", "custom", "Review completeness and risks")],
        "risk_summary": [("risk register", "custom", "Summarize assumptions and residual risks")],
        "scope_traceability": [("trace model", "custom", "Preserve explicit user scope")],
        "assumption_capture": [("assumption log", "custom", "Expose defaulted decisions")],
        "custom_implementation": [("custom implementation", "custom", "Implement per requirement")],
    }
    rows = []
    for item in capability_map.get("capability_map", []):
        for capability in item.get("capabilities", []):
            candidates = [
                {"name": name, "ecosystem": ecosystem, "fit_reason": reason}
                for name, ecosystem, reason in catalog.get(capability, catalog["custom_implementation"])
            ]
            rows.append({"feature_id": item.get("feature_id"), "feature": item.get("feature"), "capability": capability, "candidates": candidates})
    return {"tech_candidates": rows}


def score_candidate(candidate: dict[str, Any]) -> float:
    ecosystem = str(candidate.get("ecosystem", ""))
    return {"custom": 0.78, "python": 0.82, "spec": 0.75}.get(ecosystem, 0.7)


def build_tech_decisions(tech_candidates: dict[str, Any]) -> dict[str, Any]:
    decisions = []
    for row in tech_candidates.get("tech_candidates", []):
        candidates = row.get("candidates", [])
        if not candidates:
            continue
        best = max(candidates, key=score_candidate)
        decisions.append(
            {
                "feature_id": row.get("feature_id"),
                "feature": row.get("feature"),
                "capability": row.get("capability"),
                "selected": best,
                "decision_type": "custom" if best.get("ecosystem") == "custom" else "library_or_spec",
                "score": score_candidate(best),
            }
        )
    return {"tech_decisions": decisions}


def build_architecture_mmd(requirement: str = "") -> str:
    return """flowchart TD
  User[User Request] --> Requirement[Requirement Agent]
  Requirement --> IO[IO Contract Agent]
  IO --> Gap[Gap Agent]
  Gap --> Feature[Feature Agent]
  Feature --> Capability[Capability Agent]
  Capability --> Tech[Tech Decision Agent]
  Tech --> Blueprint[Blueprint Artifacts]
  Blueprint --> Review[Review Report]
"""


def build_api_yaml(requirement: str = "") -> str:
    return """openapi: 3.1.0
info:
  title: CGNK Generated Project API
  version: 1.0.0
paths:
  /api/projects:
    post:
      summary: Create a project from a natural-language requirement
  /api/projects/{project_id}/blueprint:
    get:
      summary: Retrieve generated blueprint artifacts
"""


def build_db_schema_sql(requirement: str = "") -> str:
    return """CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  goal TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE artifacts (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  artifact_type TEXT NOT NULL,
  path TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def build_frontend_pages(requirement: str = "") -> dict[str, Any]:
    return {
        "pages": [
            {"id": "project_intake", "purpose": "Capture project requirement and assumptions."},
            {"id": "blueprint_review", "purpose": "Review generated blueprint, tasks, risks, and artifacts."},
            {"id": "artifact_browser", "purpose": "Open emitted JSON, Markdown, Mermaid, YAML, SQL, and CSV artifacts."},
        ]
    }


def build_task_backlog(feature_spec: dict[str, Any]) -> list[dict[str, Any]]:
    tasks = []
    for feature in feature_spec.get("features", []):
        tasks.append(
            {
                "id": "T" + str(len(tasks) + 1).zfill(3),
                "title": f"Implement {feature.get('name', 'feature')}",
                "module": str(feature.get("name", "feature")).lower().replace(" ", "_"),
                "priority": feature.get("priority", "Should"),
                "depends_on": tasks[-1]["id"] if tasks else "",
                "acceptance_criteria": "Inputs and outputs are explicit. | Generated artifact validates. | Traceability is preserved.",
                "output": ";".join(str(x) for x in feature.get("outputs", [])),
            }
        )
    return tasks


def task_backlog_csv(tasks: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    fieldnames = ["id", "title", "module", "priority", "depends_on", "acceptance_criteria", "output"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for task in tasks:
        writer.writerow({key: task.get(key, "") for key in fieldnames})
    return output.getvalue()


def build_prd(requirement: str, requirement_spec: dict[str, Any], feature_spec: dict[str, Any], tech_decisions: dict[str, Any]) -> str:
    project_type = requirement_spec.get("project_type", {}).get("value", "custom_application")
    users = ", ".join(str(x) for x in requirement_spec.get("target_users", {}).get("value", []))
    features = "\n".join(f"- {row.get('name')}: {row.get('description')}" for row in feature_spec.get("features", []))
    decisions = "\n".join(
        f"- {row.get('capability')}: {row.get('selected', {}).get('name')} ({row.get('decision_type')})"
        for row in tech_decisions.get("tech_decisions", [])[:12]
    )
    return f"""# Requirement Blueprint PRD

## Raw Requirement

{clean_text(requirement)}

## Project Type

{project_type}

## Target Users

{users}

## Core Features

{features}

## Technology Decisions

{decisions}

## Acceptance

- The blueprint includes requirement, I/O, feature, capability, technology, architecture, API, database, frontend, task, and review artifacts.
- Level 3 gaps must be resolved or explicitly defaulted before treating the blueprint as final.
- External network or provider actions require explicit runtime flags.
"""


def build_review_report(blueprint_parts: dict[str, Any]) -> dict[str, Any]:
    gap = blueprint_parts.get("gap_analysis", {})
    open_items = [row for row in gap.get("gap_items", []) if row.get("status") != "resolved"]
    return {
        "status": "pass" if not any(row.get("severity") == "Level 3" for row in open_items) else "needs_confirmation",
        "open_gaps": open_items,
        "risk_summary": [
            "Generated artifacts depend on assumptions when user input is incomplete.",
            "Technology decisions are planning defaults until implementation validates them.",
        ],
    }


def build_requirement_blueprint(
    requirement: str,
    answers: list[dict[str, str]] | None = None,
    *,
    assume_defaults: bool = False,
    goal_spec: dict[str, Any] | None = None,
    project_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mapped_answers = answer_map(answers)
    requirement_spec = build_requirement_spec(requirement, mapped_answers)
    io_contract = build_io_contract(requirement, requirement_spec, mapped_answers)
    gap_analysis = build_gap_analysis(requirement, mapped_answers, assume_defaults)
    feature_spec = build_feature_spec(requirement, mapped_answers)
    canonical_goal_spec = goal_spec if isinstance(goal_spec, dict) else {}
    canonical_project_plan = project_plan if isinstance(project_plan, dict) else {}
    if canonical_goal_spec.get("status") == "PASS":
        requirement_spec["project_type"] = source_value(
            canonical_goal_spec.get("domain", "custom_local_application"),
            "canonical_goal_spec",
            1.0,
        )
        requirement_spec["domain"] = source_value(
            canonical_goal_spec.get("domain", "custom_local_application"),
            "canonical_goal_spec",
            1.0,
        )
        requirement_spec["required_features"] = source_value(
            list(canonical_goal_spec.get("capabilities", [])),
            "canonical_goal_spec",
            1.0,
        )
        requirement_spec["business_goal"] = source_value(
            canonical_goal_spec.get("goal", requirement),
            "canonical_goal_spec",
            1.0,
        )
        requirement_spec["scenarios"] = [
            source_value(flow, "canonical_goal_spec", 1.0)
            for flow in canonical_goal_spec.get("user_flows", [])
        ]
        io_contract["domain_entities"] = list(canonical_goal_spec.get("entities", []))
        io_contract["declared_interfaces"] = list(canonical_goal_spec.get("interfaces", []))
        feature_spec = {
            "features": [
                {
                    "id": f"F{index:03d}",
                    "name": str(capability).replace("_", " ").title(),
                    "description": f"Implement canonical GoalSpec capability: {capability}.",
                    "priority": "Must",
                    "inputs": ["goal_spec"],
                    "outputs": [str(capability)],
                    "source_type": "canonical_goal_spec",
                }
                for index, capability in enumerate(canonical_goal_spec.get("capabilities", []), 1)
            ]
        }
    capability_map = build_capability_map(feature_spec)
    tech_candidates = build_tech_candidates(capability_map)
    tech_decisions = build_tech_decisions(tech_candidates)
    tasks = build_task_backlog(feature_spec)
    parts = {
        "requirement_spec": requirement_spec,
        "io_contract": io_contract,
        "gap_analysis": gap_analysis,
        "feature_spec": feature_spec,
        "capability_map": capability_map,
        "tech_candidates": tech_candidates,
        "tech_decisions": tech_decisions,
        "architecture_mmd": build_architecture_mmd(requirement),
        "api_openapi_yaml": build_api_yaml(requirement),
        "db_schema_sql": build_db_schema_sql(requirement),
        "frontend_pages": (
            {
                "pages": [
                    {"id": str(interface), "purpose": f"Expose {str(interface).replace('_', ' ')} behavior from the canonical GoalSpec."}
                    for interface in canonical_goal_spec.get("interfaces", [])
                ]
            }
            if canonical_goal_spec.get("status") == "PASS"
            else build_frontend_pages(requirement)
        ),
        "task_backlog": tasks,
        "task_backlog_csv": task_backlog_csv(tasks),
        "canonical_goal_spec": canonical_goal_spec,
        "canonical_project_plan": canonical_project_plan,
    }
    parts["prd_md"] = build_prd(requirement, requirement_spec, feature_spec, tech_decisions)
    parts["review_report"] = build_review_report(parts)
    return {
        "kind": "RequirementBlueprint",
        "status": "pass" if gap_analysis.get("can_continue") else "needs_confirmation",
        "generated_at": now(),
        "raw_requirement": requirement,
        "answers": answers or [],
        **parts,
    }


def export_requirement_blueprint_files(blueprint: dict[str, Any]) -> dict[str, str]:
    return {
        "requirement_spec.json": json.dumps(blueprint["requirement_spec"], ensure_ascii=False, indent=2) + "\n",
        "io_contract.json": json.dumps(blueprint["io_contract"], ensure_ascii=False, indent=2) + "\n",
        "gap_analysis.json": json.dumps(blueprint["gap_analysis"], ensure_ascii=False, indent=2) + "\n",
        "feature_spec.json": json.dumps(blueprint["feature_spec"], ensure_ascii=False, indent=2) + "\n",
        "capability_map.json": json.dumps(blueprint["capability_map"], ensure_ascii=False, indent=2) + "\n",
        "tech_candidates.json": json.dumps(blueprint["tech_candidates"], ensure_ascii=False, indent=2) + "\n",
        "tech_decisions.json": json.dumps(blueprint["tech_decisions"], ensure_ascii=False, indent=2) + "\n",
        "architecture.mmd": blueprint["architecture_mmd"],
        "api.openapi.yaml": blueprint["api_openapi_yaml"],
        "db_schema.sql": blueprint["db_schema_sql"],
        "frontend_pages.json": json.dumps(blueprint["frontend_pages"], ensure_ascii=False, indent=2) + "\n",
        "task_backlog.csv": blueprint["task_backlog_csv"],
        "prd.md": blueprint["prd_md"],
        "review_report.json": json.dumps(blueprint["review_report"], ensure_ascii=False, indent=2) + "\n",
    }


def write_requirement_blueprint_outputs(base_dir: pathlib.Path, blueprint: dict[str, Any]) -> dict[str, str]:
    refs: dict[str, str] = {}
    for name, content in export_requirement_blueprint_files(blueprint).items():
        path = base_dir / name
        write_text(path, content)
        refs[name] = str(path)
    return refs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirement", required=True)
    parser.add_argument("--answers-json", default="[]")
    parser.add_argument("--assume-defaults", action="store_true")
    parser.add_argument("--outputs-dir", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    answers = json.loads(args.answers_json)
    blueprint = build_requirement_blueprint(args.requirement, answers, assume_defaults=args.assume_defaults)
    if args.outputs_dir:
        blueprint["output_refs"] = write_requirement_blueprint_outputs(pathlib.Path(args.outputs_dir), blueprint)
    if args.json:
        print(json.dumps(blueprint, ensure_ascii=False, indent=2))
    else:
        print(f"status={blueprint['status']}")
        print(f"project_type={blueprint['requirement_spec']['project_type']['value']}")
        if args.outputs_dir:
            print(f"outputs_dir={args.outputs_dir}")
    return 0 if blueprint["status"] in {"pass", "needs_confirmation"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
