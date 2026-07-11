#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
from datetime import datetime, timezone
from typing import Any


PLANNING_DOCS = ("product_brief.md", "technical_plan.md", "interaction_design.md", "acceptance_matrix.md")


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def as_lines(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        return [f"{key}: {val}" for key, val in value.items() if str(val).strip()]
    text = str(value or "").strip()
    return [text] if text else []


def bullets(items: list[str], fallback: str) -> str:
    values = items or [fallback]
    return "\n".join(f"- {item}" for item in values)


def first_text(*values: Any, fallback: str) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list) and value:
            return "; ".join(str(item).strip() for item in value if str(item).strip())
    return fallback


def load_inputs(run_dir: pathlib.Path) -> dict[str, Any]:
    requirement_dir = run_dir / "requirement_decision"
    discovery_dir = run_dir / "discovery"
    return {
        "selected_requirement": read_json(requirement_dir / "selected_requirement.json"),
        "mvp_scope_text": read_text(requirement_dir / "mvp_scope.md"),
        "non_goals_text": read_text(requirement_dir / "non_goals.md"),
        "acceptance_contract": read_json(requirement_dir / "acceptance_contract.json"),
        "complexity_project_contract": read_json(discovery_dir / "complexity_project_contract.json"),
        "requirement_dir": requirement_dir,
        "discovery_dir": discovery_dir,
    }


def selected_requirement_id(selected: dict[str, Any]) -> str:
    return str(selected.get("selected_requirement_id") or selected.get("id") or "selected_requirement").strip()


def selected_requirement_name(selected: dict[str, Any]) -> str:
    return str(selected.get("name") or selected.get("selected_requirement_name") or selected_requirement_id(selected)).strip()


def product_brief(inputs: dict[str, Any]) -> str:
    selected = inputs["selected_requirement"]
    acceptance = inputs["acceptance_contract"]
    contract = inputs["complexity_project_contract"]
    requirement_id = selected_requirement_id(selected)
    name = selected_requirement_name(selected)
    need = first_text(selected.get("need"), selected.get("interpreted_need"), selected.get("summary"), fallback="A local-first product must convert the customer's broad goal into a clear, testable workflow.")
    target_user = first_text(selected.get("target_user"), contract.get("target_user"), fallback="Operators who need repeatable local project execution with visible evidence.")
    shape = first_text(selected.get("product_shape"), contract.get("selected_product_shape"), contract.get("selected_project_id"), fallback="A local workbench with planning evidence before implementation.")
    success = as_lines(selected.get("success_definition")) or as_lines(acceptance.get("acceptance_criteria")) or [
        "The selected requirement is traceable to product scope, planning artifacts, implementation evidence, and delivery gates."
    ]
    assumptions = as_lines(selected.get("assumptions")) or [
        "Provider output may be unavailable, so deterministic product planning can be used without claiming implementation completion.",
        "Planning artifacts are contractual evidence only; they are not code, screenshot, or final delivery evidence.",
    ]
    return f"""# Product Brief

Planning materialization status: deterministic_contract_planning, not implementation evidence.

## Selected Requirement
- id: {requirement_id}
- name: {name}
- source: selected_requirement.json

## Interpreted Customer Need
{need}

## Target User
{target_user}

## Core Problem
The customer needs the broad request converted into a bounded product contract before implementation starts. The core problem is to preserve Requirement Decision First while preventing planning gaps from becoming fake implementation or delivery PASS results.

## Selected Product Shape
{shape}

## MVP Scope
Source: mvp_scope.md

{inputs['mvp_scope_text'].strip() or bullets(as_lines(selected.get('mvp_scope')), 'MVP scope is defined by selected_requirement.json and acceptance_contract.json.')}

## Non-Goals
Source: non_goals.md

{inputs['non_goals_text'].strip() or bullets(as_lines(selected.get('non_goals')), 'Do not treat planning docs as completed implementation or final delivery.')}

## Success Definition
{bullets(success, 'Product planning is complete enough to guide implementation without relaxing delivery truth.')}

## Assumptions
{bullets(assumptions, 'Planning is contract-driven and must be verified before implementation.')}

## References
- selected_requirement.json
- acceptance_contract.json
- mvp_scope.md
- non_goals.md
"""


def technical_plan(inputs: dict[str, Any]) -> str:
    contract = inputs["complexity_project_contract"]
    acceptance = inputs["acceptance_contract"]
    modules = as_lines(contract.get("required_modules")) or [
        "orchestrator.py as the single workflow coordinator",
        "stages.py as the shared implementation stage library",
        "CLI entrypoint calling the shared orchestrator",
        "GUI entrypoint calling the shared orchestrator",
        "artifact validators for stage outputs and traceability",
    ]
    stages = as_lines(contract.get("required_pipeline_stages")) or as_lines(contract.get("pipeline_stages")) or [
        "ingest_video",
        "extract_audio",
        "chunk_audio",
        "transcribe_audio",
        "analyze_segments",
        "select_segments",
        "render_clips",
        "export_results",
    ]
    artifacts = as_lines(contract.get("required_stage_artifacts")) or [
        "stage_plan.json",
        "media_manifest.json",
        "audio_chunk_manifest.json",
        "transcript_merged.json",
        "segment_analysis.json",
        "selected_segments.json",
        "clip_manifest.json",
        "export_results.json",
    ]
    risks = [
        "Provider output may omit required modules or stage artifacts.",
        "GUI and CLI can drift if they do not share the same orchestrator and stages.",
        "External media tooling or model access may be unavailable and must be represented as honest degraded mode.",
        "Delivery evidence remains separate from product planning evidence.",
    ]
    criteria = as_lines(acceptance.get("acceptance_criteria")) or [
        "requirement_decision, product_contract, implementation, and delivery statuses must be evaluated independently."
    ]
    return f"""# Technical Plan

Planning materialization status: deterministic_contract_planning, not implementation evidence.

## Architecture Overview
The implementation should be local-first and contract-driven. Product planning artifacts are created from selected_requirement.json, acceptance_contract.json, and complexity_project_contract.json before implementation. Runtime code must later use one orchestrator and one stages module shared by GUI and CLI.

## Required Modules
{bullets(modules, 'Required modules come from complexity_project_contract.json.')}

## Data/Artifact Flow
Inputs move from customer goal and selected_requirement.json into product planning docs, then into implementation artifacts. Stage artifacts must flow downstream with upstream_artifacts references so later files can prove where their inputs came from.

Required stage artifacts:
{bullets(artifacts, 'Stage artifact list comes from complexity_project_contract.json.')}

## Pipeline Stages
{bullets(stages, 'Pipeline stages come from complexity_project_contract.json.')}

## Local-First/Degraded Mode Strategy
When ffmpeg, provider models, or media dependencies are unavailable, the implementation must expose honest degraded mode. Degraded mode can write blockers and partial artifacts, but it must not claim real processing success, screenshot evidence, or final delivery completion.

## Implementation Risks
{bullets(risks, 'Implementation risks must be tracked before delivery.')}

## Verification Strategy
{bullets(criteria, 'Acceptance criteria come from acceptance_contract.json.')}
- Product planning can PASS while implementation remains FAIL.
- Implementation can PASS only after required structure and artifact schemas exist.
- Delivery can PASS only with final bundle, screenshot, run_dir, README, TEST_REPORT, and DELIVERY_NOTES.

## References
- acceptance_contract.json
- complexity_project_contract.json
- selected_requirement.json
"""


def interaction_design(inputs: dict[str, Any]) -> str:
    selected = inputs["selected_requirement"]
    contract = inputs["complexity_project_contract"]
    target_user = first_text(selected.get("target_user"), contract.get("target_user"), fallback="Local operators who need visible progress and evidence.")
    views = as_lines(contract.get("required_views")) or [
        "Import/source selection view",
        "Pipeline progress view",
        "Artifact/evidence review view",
        "Degraded mode and blocker view",
        "Export/readiness view",
    ]
    interactions = [
        "Start or resume the shared pipeline through GUI or CLI.",
        "Inspect stage status, counts, input paths, output paths, and upstream artifacts.",
        "See blockers when provider, model, or media tooling is unavailable.",
        "Review known gaps before final delivery is attempted.",
    ]
    return f"""# Interaction Design

Planning materialization status: deterministic_contract_planning, not implementation evidence.

## Target User
{target_user}

## Primary User Journey
The user starts with a selected requirement, reviews the MVP scope, launches the same pipeline through GUI or CLI, watches stage progress, checks artifact evidence, and only treats the result as delivery-ready after strict delivery evidence exists.

## Required Pages/Views
{bullets(views, 'Required views come from selected_requirement.json and mvp_scope.md.')}

## Key Interactions
{bullets(interactions, 'Interactions must expose progress, blockers, and evidence.')}

## GUI/CLI Relationship
GUI and CLI are two control surfaces over the same orchestrator.py and stages.py. Neither surface may contain a separate implementation path. Both must expose the same pipeline state and artifact locations.

## Pipeline Progress Visibility
Every stage should show stage name, status, count, input_path, output_path, created_at, and upstream_artifacts. Progress visibility is part of implementation acceptance, not delivery completion.

## Degraded/Blocker Visibility
Degraded mode must be visible as an honest status. Missing model access, missing ffmpeg, unavailable input files, or provider failure must block fake PASS claims and remain visible in user-facing status.

## References
- selected_requirement.json
- mvp_scope.md
- non_goals.md
"""


def acceptance_matrix(inputs: dict[str, Any]) -> str:
    selected = inputs["selected_requirement"]
    acceptance = inputs["acceptance_contract"]
    requirement_id = selected_requirement_id(selected)
    criteria = as_lines(acceptance.get("acceptance_criteria")) or [
        "Requirement decision artifacts exist and are internally consistent.",
        "Product planning docs cite their upstream contracts.",
        "Implementation structure and stage artifact schemas are present before implementation PASS.",
        "Delivery has final bundle, screenshot, run_dir, README, TEST_REPORT, and DELIVERY_NOTES before delivery PASS.",
    ]
    non_goals = as_lines(selected.get("non_goals")) or [inputs["non_goals_text"].strip() or "Planning docs must not be treated as completed implementation or delivery."]
    return f"""# Acceptance Matrix

Planning materialization status: deterministic_contract_planning, not implementation evidence.

## Requirement ID
{requirement_id}

## Acceptance Criteria
{bullets(criteria, 'Acceptance criteria come from acceptance_contract.json.')}

## Evidence Required
- requirement_decision: selected_requirement.json, mvp_scope.md, non_goals.md, acceptance_contract.json
- product_contract: product_brief.md, technical_plan.md, interaction_design.md, acceptance_matrix.md
- implementation: orchestrator.py, stages.py, CLI, GUI, shared core, stage artifact schema, upstream/downstream traceability
- delivery: README.md, TEST_REPORT.md, DELIVERY_NOTES.md, screenshot, final_project_bundle.zip, run_dir

## Layer Mapping
| Layer | Must pass only when | Evidence |
| --- | --- | --- |
| requirement_decision | customer need is selected and scoped | selected_requirement.json and acceptance_contract.json |
| product_contract | planning docs are complete and contract-driven | four planning docs with references |
| implementation | runnable structure and artifact schemas exist | shared orchestrator/stages, CLI, GUI, stage artifacts |
| delivery | strict final evidence exists | zip, screenshot, reports, run_dir |

## Must-Have vs Should-Have
- Must-have: independent layer gates, contract-driven planning docs, no fake PASS, strict delivery truth.
- Should-have: richer provider-authored prose when live provider succeeds, while deterministic planning remains acceptable for no-live product planning.

## Non-Goal Exclusions
{bullets(non_goals, 'Non-goals come from selected_requirement.json and non_goals.md.')}

## Fake PASS Prevention Checks
- requirement_decision PASS must not make product_contract PASS.
- product_contract PASS must not make implementation PASS.
- implementation PASS must not make delivery PASS.
- Planning docs are not implementation evidence.
- Planning docs are not screenshot, run_dir, or final_project_bundle.zip evidence.

## References
- acceptance_contract.json
- selected_requirement.json
- complexity_project_contract.json
"""


GENERATORS = {
    "product_brief.md": product_brief,
    "technical_plan.md": technical_plan,
    "interaction_design.md": interaction_design,
    "acceptance_matrix.md": acceptance_matrix,
}


def materialize(*, project_dir: pathlib.Path, run_dir: pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    run = pathlib.Path(run_dir)
    inputs = load_inputs(run)
    project.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name in PLANNING_DOCS:
        text = GENERATORS[name](inputs).rstrip() + "\n"
        path = project / name
        path.write_text(text, encoding="utf-8")
        written.append(str(path))
    manifest = {
        "status": "PASS",
        "mode": "deterministic_contract_planning",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_dir": str(project),
        "run_dir": str(run),
        "written": written,
        "not_implementation_evidence": True,
        "not_delivery_evidence": True,
    }
    (project / "planning_materialization_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    result = materialize(project_dir=pathlib.Path(args.project_dir), run_dir=pathlib.Path(args.run_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
