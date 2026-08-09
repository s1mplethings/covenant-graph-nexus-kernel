#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any


DISCOVERY_FILES = [
    "discovery_brief.md",
    "candidate_directions.json",
    "candidate_scorecard.json",
    "selected_project_direction.json",
    "rejected_options.md",
    "complexity_project_contract.json",
]


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def iter_files(project_dir: pathlib.Path) -> list[pathlib.Path]:
    if not project_dir.exists():
        return []
    return [path for path in project_dir.rglob("*") if path.is_file()]


def find_by_name(files: list[pathlib.Path], name: str) -> list[pathlib.Path]:
    target = name.replace("\\", "/").strip("/").lower()
    if "/" in target:
        return [
            path
            for path in files
            if path.as_posix().lower() == target or path.as_posix().lower().endswith("/" + target)
        ]
    return [path for path in files if path.name.lower() == target]


def read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def has_terms(path: pathlib.Path, terms: list[str]) -> bool:
    text = read_text(path).lower()
    return any(term.lower() in text for term in terms)


def locate_discovery_dir(run_dir: pathlib.Path | None, project_dir: pathlib.Path | None) -> pathlib.Path | None:
    candidates: list[pathlib.Path] = []
    if run_dir:
        candidates.append(run_dir / "discovery")
    if project_dir:
        candidates.extend([project_dir / "discovery", project_dir / "run_dir" / "discovery"])
    for candidate in candidates:
        if (candidate / "complexity_project_contract.json").exists():
            return candidate
    return candidates[0] if candidates else None


def validate_discovery(discovery_dir: pathlib.Path | None) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    if discovery_dir is None:
        return {}, ["discovery_dir_missing"]
    for name in DISCOVERY_FILES:
        path = discovery_dir / name
        if not path.exists() or path.stat().st_size == 0:
            blockers.append(f"{name}_missing")
    candidates = read_json(discovery_dir / "candidate_directions.json")
    scorecard = read_json(discovery_dir / "candidate_scorecard.json")
    selected = read_json(discovery_dir / "selected_project_direction.json")
    contract = read_json(discovery_dir / "complexity_project_contract.json")
    raw_candidates = candidates.get("candidates", [])
    if not isinstance(raw_candidates, list) or len(raw_candidates) < 3:
        blockers.append("candidate_directions_lt_3")
    for candidate in raw_candidates if isinstance(raw_candidates, list) else []:
        if not isinstance(candidate, dict):
            blockers.append("candidate_direction_invalid")
            continue
        for key in ("complexity_score", "local_first_feasibility", "delivery_feasibility", "testability_score", "screenshot_feasibility"):
            if key not in candidate:
                blockers.append(f"candidate_{candidate.get('id', 'unknown')}_{key}_missing")
        if candidate.get("id") == selected.get("selected_id"):
            if int(candidate.get("complexity_score", 0)) < 60:
                blockers.append("selected_direction_low_complexity")
            if candidate.get("demo_degradation_risk") == "high":
                blockers.append("selected_direction_demo_degradation_high")
            if candidate.get("fake_pass_risk") == "high":
                blockers.append("selected_direction_fake_pass_high")
    if not scorecard.get("scores"):
        blockers.append("candidate_scorecard_scores_missing")
    if not selected.get("selected_id"):
        blockers.append("selected_project_direction_missing")
    if contract.get("contract_id") != "complexity_project_contract_v1":
        blockers.append("complexity_project_contract_id_invalid")
    architecture_mode = str(contract.get("architecture_mode", "")).strip()
    for key in ("required_pipeline_stages", "required_delivery_evidence"):
        value = contract.get(key)
        if not isinstance(value, list) or not value:
            blockers.append(f"contract_{key}_missing")
    stage_artifacts = contract.get("required_stage_artifacts")
    if not isinstance(stage_artifacts, list):
        blockers.append("contract_required_stage_artifacts_missing")
    elif architecture_mode != "browser_local_static" and not stage_artifacts:
        blockers.append("contract_required_stage_artifacts_missing")
    return contract, blockers


def detect_cli_gui_shared(project_dir: pathlib.Path, files: list[pathlib.Path]) -> tuple[bool, bool, bool]:
    cli_terms = ["argparse", "click", "typer", "__main__", "subparsers"]
    gui_terms = ["tkinter", "streamlit", "gradio", "pyqt", "pyside", "customtkinter", "flask", "fastapi"]
    cli = [
        path
        for path in files
        if path.suffix == ".py"
        and ("cli" in path.name.lower() or path.name.lower() in {"main.py", "__main__.py"})
        and has_terms(path, cli_terms)
    ]
    gui = [
        path
        for path in files
        if path.suffix == ".py"
        and ("gui" in path.name.lower() or "app" in path.name.lower() or "ui" in path.name.lower())
        and has_terms(path, gui_terms)
    ]
    cli_shared = any(has_terms(path, ["orchestrator", "stages"]) for path in cli)
    gui_shared = any(has_terms(path, ["orchestrator", "stages"]) for path in gui)
    core = bool(find_by_name(files, "orchestrator.py") and find_by_name(files, "stages.py"))
    return bool(cli), bool(gui), bool(core and cli_shared and gui_shared)


def validate_project(
    project_dir: pathlib.Path | None,
    run_dir: pathlib.Path | None,
    contract: dict[str, Any],
    *,
    require_final_bundle: bool = True,
) -> list[str]:
    blockers: list[str] = []
    if project_dir is None:
        return blockers
    project = pathlib.Path(project_dir)
    files = iter_files(project)
    if not project.exists():
        return ["project_dir_missing"]
    for name in contract.get("required_planning_docs", []):
        if not find_by_name(files, str(name)):
            blockers.append(f"{name}_missing")
    for name in contract.get("required_core_files", []):
        if not find_by_name(files, str(name)):
            blockers.append(f"{name}_missing")
    has_cli, has_gui, shared = detect_cli_gui_shared(project, files)
    if "cli" in contract.get("required_interfaces", []) and not has_cli:
        blockers.append("cli_entry_missing")
    if "gui" in contract.get("required_interfaces", []) and not has_gui:
        blockers.append("gui_entry_missing")
    if contract.get("requires_shared_gui_cli_core") and not shared:
        blockers.append("gui_cli_shared_core_missing")
    for artifact in contract.get("required_stage_artifacts", []):
        if not find_by_name(files, str(artifact)):
            blockers.append(f"stage_artifact_missing:{artifact}")
    for name in ("README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md"):
        if not find_by_name(files, name):
            blockers.append(f"{name}_missing")
    if run_dir is None or not pathlib.Path(run_dir).exists():
        blockers.append("run_dir_missing")
    if not any(path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and "screenshot" in path.as_posix().lower() for path in files):
        blockers.append("screenshot_missing")
    if require_final_bundle and not (project / "final_project_bundle.zip").exists():
        blockers.append("final_project_bundle.zip_missing")
    return blockers


def validate(
    *,
    discovery_dir: pathlib.Path | None = None,
    run_dir: pathlib.Path | None = None,
    project_dir: pathlib.Path | None = None,
    require_final_bundle: bool = True,
) -> dict[str, Any]:
    resolved_discovery = discovery_dir or locate_discovery_dir(run_dir, project_dir)
    contract, blockers = validate_discovery(resolved_discovery)
    blockers.extend(
        validate_project(
            project_dir,
            run_dir,
            contract,
            require_final_bundle=require_final_bundle,
        )
    )
    status = "pass" if not blockers else "needs_rework"
    return {
        "status": status,
        "recommendation": (
            "PASS_FINAL"
            if status == "pass" and require_final_bundle
            else "PASS_CANDIDATE"
            if status == "pass"
            else "NEEDS_REWORK"
        ),
        "blockers": blockers,
        "metadata": {
            "discovery_dir": str(resolved_discovery) if resolved_discovery else "",
            "project_dir": str(project_dir or ""),
            "run_dir": str(run_dir or ""),
            "contract_id": contract.get("contract_id", ""),
            "selected_project_id": contract.get("selected_project_id", ""),
            "require_final_bundle": require_final_bundle,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery-dir", default="")
    parser.add_argument("--run-dir", default="")
    parser.add_argument("--project-dir", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = validate(
        discovery_dir=pathlib.Path(args.discovery_dir) if args.discovery_dir else None,
        run_dir=pathlib.Path(args.run_dir) if args.run_dir else None,
        project_dir=pathlib.Path(args.project_dir) if args.project_dir else None,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"COMPLEXITY_PROJECT_CONTRACT_CHECK: {result['status'].upper()}")
        for blocker in result.get("blockers", []):
            print(f"- {blocker}")
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
