#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cgkn_project_management import (  # noqa: E402
    close_iteration,
    new_enterprise_experience_pack,
    new_iteration,
    new_project_management_pack,
    record_experience_usage,
    render_enterprise_experience_markdown,
    render_project_management_markdown,
    retrieve_experience,
    validate_enterprise_experience_pack,
    validate_iteration,
    validate_project_management_pack,
)


def read_json(path: pathlib.Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def command_init(args: argparse.Namespace) -> int:
    target = pathlib.Path(args.output).resolve()
    target.mkdir(parents=True, exist_ok=True)
    management = new_project_management_pack(
        project_id=args.project_id,
        project_name=args.project_name,
        goal=args.goal,
        requirements_uncertainty=args.requirements_uncertainty,
        technical_uncertainty=args.technical_uncertainty,
        criticality=args.criticality,
    )
    experience = new_enterprise_experience_pack(args.organization)
    write_json(target / "project_management.json", management)
    write_json(target / "enterprise_experience.json", experience)
    (target / "PROJECT_MANAGEMENT.md").write_text(
        render_project_management_markdown(management),
        encoding="utf-8",
    )
    (target / "ENTERPRISE_EXPERIENCE.md").write_text(
        render_enterprise_experience_markdown(experience),
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "output": str(target)}, ensure_ascii=False))
    return 0


def command_validate(args: argparse.Namespace) -> int:
    target = pathlib.Path(args.path).resolve()
    doc = read_json(target)
    kind = doc.get("kind")
    if kind == "CGKNAdaptiveProjectManagementPack":
        result = validate_project_management_pack(doc)
    elif kind == "CGKNAdaptiveIteration":
        project = read_json(pathlib.Path(args.project_pack).resolve()) if args.project_pack else None
        result = validate_iteration(doc, project)
    elif kind == "CGKNEnterpriseExperiencePack":
        result = validate_enterprise_experience_pack(doc)
    else:
        result = {
            "kind": "CGKNManagementValidationResult",
            "status": "FAIL",
            "errors": [{"code": "KIND_INVALID", "message": f"unsupported kind: {kind}", "path": "kind"}],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


def command_retrieve(args: argparse.Namespace) -> int:
    pack = read_json(pathlib.Path(args.experience_pack).resolve())
    result = retrieve_experience(
        pack,
        tags=args.tag,
        max_items=args.max_items,
        include_validated=not args.approved_only,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_start_iteration(args: argparse.Namespace) -> int:
    project_path = pathlib.Path(args.project_pack).resolve()
    project = read_json(project_path)
    iteration = new_iteration(
        project,
        iteration_id=args.iteration_id,
        goal=args.goal,
        backlog_item_ids=args.backlog_item,
    )
    iteration["workflow_state"] = "active"
    validation = validate_iteration(iteration, project)
    if validation["status"] != "PASS":
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return 1
    output = pathlib.Path(args.output).resolve()
    write_json(output, iteration)
    try:
        reference = output.relative_to(project_path.parent).as_posix()
    except ValueError:
        reference = str(output)
    if reference not in project.setdefault("iteration_refs", []):
        project["iteration_refs"].append(reference)
    selected = set(iteration["backlog_item_ids"])
    for item in project.get("product_backlog", []):
        if isinstance(item, dict) and item.get("id") in selected:
            item["state"] = "active"
    project["workflow_state"] = "delivering"
    write_json(project_path, project)
    print(json.dumps({"status": "PASS", "iteration": str(output), "project_pack": str(project_path)}, ensure_ascii=False))
    return 0


def command_close_iteration(args: argparse.Namespace) -> int:
    iteration_path = pathlib.Path(args.path).resolve()
    iteration = read_json(iteration_path)
    closed = close_iteration(
        iteration,
        evidence_status=args.evidence_status,
        review_outcome=args.review_outcome,
        evidence_refs=args.evidence_ref,
        feedback=args.feedback,
        worked=args.worked,
        did_not_work=args.did_not_work,
        experiments=args.experiment,
    )
    project = read_json(pathlib.Path(args.project_pack).resolve()) if args.project_pack else None
    validation = validate_iteration(closed, project)
    if validation["status"] != "PASS":
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return 1
    write_json(iteration_path, closed)
    if project is not None:
        accepted = set(closed["review"]["accepted_backlog_item_ids"])
        for item in project.get("product_backlog", []):
            if isinstance(item, dict) and item.get("id") in closed["backlog_item_ids"]:
                item["state"] = "done" if item.get("id") in accepted else "ready"
        for experiment in closed["retrospective"]["experiments"]:
            if experiment not in project.setdefault("improvement_backlog", []):
                project["improvement_backlog"].append(experiment)
        write_json(pathlib.Path(args.project_pack).resolve(), project)
    print(json.dumps({"status": "PASS", "iteration": str(iteration_path)}, ensure_ascii=False))
    return 0


def command_record_usage(args: argparse.Namespace) -> int:
    pack_path = pathlib.Path(args.experience_pack).resolve()
    pack = read_json(pack_path)
    updated = record_experience_usage(
        pack,
        experience_id=args.experience_id,
        project_id=args.project_id,
        iteration_id=args.iteration_id,
        applied=args.applied,
        outcome=args.outcome,
        evidence_refs=args.evidence_ref,
    )
    validation = validate_enterprise_experience_pack(updated)
    if validation["status"] != "PASS":
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return 1
    write_json(pack_path, updated)
    print(json.dumps({"status": "PASS", "experience_pack": str(pack_path)}, ensure_ascii=False))
    return 0


def command_render(args: argparse.Namespace) -> int:
    output = pathlib.Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.project_pack:
        pack = read_json(pathlib.Path(args.project_pack).resolve())
        output.write_text(render_project_management_markdown(pack), encoding="utf-8")
    else:
        pack = read_json(pathlib.Path(args.experience_pack).resolve())
        output.write_text(render_enterprise_experience_markdown(pack), encoding="utf-8")
    print(json.dumps({"status": "PASS", "output": str(output)}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage tailored PMP, agile, quality, and enterprise experience artifacts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    init.add_argument("--output", required=True)
    init.add_argument("--project-id", required=True)
    init.add_argument("--project-name", required=True)
    init.add_argument("--goal", required=True)
    init.add_argument("--organization", default="CGKN")
    init.add_argument("--requirements-uncertainty", choices=["low", "medium", "high"], default="medium")
    init.add_argument("--technical-uncertainty", choices=["low", "medium", "high"], default="medium")
    init.add_argument("--criticality", choices=["low", "medium", "high"], default="medium")
    init.set_defaults(func=command_init)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--path", required=True)
    validate.add_argument("--project-pack")
    validate.set_defaults(func=command_validate)

    retrieve = subparsers.add_parser("retrieve")
    retrieve.add_argument("--experience-pack", required=True)
    retrieve.add_argument("--tag", action="append", default=[])
    retrieve.add_argument("--max-items", type=int, default=8)
    retrieve.add_argument("--approved-only", action="store_true")
    retrieve.set_defaults(func=command_retrieve)

    start = subparsers.add_parser("start-iteration")
    start.add_argument("--project-pack", required=True)
    start.add_argument("--iteration-id", required=True)
    start.add_argument("--goal", required=True)
    start.add_argument("--backlog-item", action="append", required=True)
    start.add_argument("--output", required=True)
    start.set_defaults(func=command_start_iteration)

    close = subparsers.add_parser("close-iteration")
    close.add_argument("--path", required=True)
    close.add_argument("--project-pack")
    close.add_argument(
        "--evidence-status",
        required=True,
        choices=[
            "PASS",
            "PASS_WITH_LIMITS",
            "BLOCKED",
            "BLOCKED_PROVIDER",
            "BLOCKED_LOCAL_MODEL",
            "BLOCKED_ENVIRONMENT",
            "NEEDS_REWORK",
            "FAIL",
        ],
    )
    close.add_argument(
        "--review-outcome",
        required=True,
        choices=["accepted", "accepted_with_limits", "rejected"],
    )
    close.add_argument("--evidence-ref", action="append", default=[])
    close.add_argument("--feedback", action="append", default=[])
    close.add_argument("--worked", action="append", default=[])
    close.add_argument("--did-not-work", action="append", default=[])
    close.add_argument("--experiment", action="append", default=[])
    close.set_defaults(func=command_close_iteration)

    usage = subparsers.add_parser("record-usage")
    usage.add_argument("--experience-pack", required=True)
    usage.add_argument("--experience-id", required=True)
    usage.add_argument("--project-id", required=True)
    usage.add_argument("--iteration-id", required=True)
    usage.add_argument("--applied", action=argparse.BooleanOptionalAction, default=True)
    usage.add_argument(
        "--outcome",
        choices=["pending", "successful", "unsuccessful", "inconclusive"],
        default="pending",
    )
    usage.add_argument("--evidence-ref", action="append", default=[])
    usage.set_defaults(func=command_record_usage)

    render = subparsers.add_parser("render")
    render_source = render.add_mutually_exclusive_group(required=True)
    render_source.add_argument("--project-pack")
    render_source.add_argument("--experience-pack")
    render.add_argument("--output", required=True)
    render.set_defaults(func=command_render)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
