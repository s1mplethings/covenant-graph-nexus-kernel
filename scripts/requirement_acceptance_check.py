#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import zipfile
from typing import Any

try:
    import stage_artifact_schema_checker
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import stage_artifact_schema_checker


REQUIREMENT_FILES = [
    "customer_goal_brief.md",
    "need_interpretations.json",
    "candidate_requirements.json",
    "requirement_scorecard.json",
    "selected_requirement.json",
    "rejected_requirements.md",
    "mvp_scope.md",
    "non_goals.md",
    "acceptance_contract.json",
    "customer_decision_summary.md",
]

PLANNING_DOC_QUALITY_TERMS = {
    "product_brief.md": [
        ["selected requirement", "selected_requirement"],
        ["interpreted customer need", "customer need"],
        ["target user"],
        ["core problem"],
        ["selected product shape", "product shape"],
        ["mvp scope"],
        ["non-goals", "non goals"],
        ["success definition"],
        ["assumptions"],
        ["selected_requirement.json"],
        ["acceptance_contract.json"],
    ],
    "technical_plan.md": [
        ["architecture overview"],
        ["required modules"],
        ["data/artifact flow", "artifact flow"],
        ["pipeline stages"],
        ["local-first", "degraded mode"],
        ["implementation risks"],
        ["verification strategy"],
        ["acceptance_contract.json"],
        ["complexity_project_contract.json"],
    ],
    "interaction_design.md": [
        ["target user"],
        ["primary user journey"],
        ["required pages/views", "required views", "pages/views"],
        ["key interactions"],
        ["gui/cli", "gui and cli"],
        ["pipeline progress visibility", "progress visibility"],
        ["degraded/blocker visibility", "blocker visibility"],
        ["selected_requirement.json"],
        ["mvp_scope.md"],
    ],
    "acceptance_matrix.md": [
        ["requirement id"],
        ["acceptance criteria"],
        ["evidence required"],
        ["requirement_decision"],
        ["product_contract"],
        ["implementation"],
        ["delivery"],
        ["must-have", "must have"],
        ["should-have", "should have"],
        ["non-goal", "non goal"],
        ["fake pass"],
        ["acceptance_contract.json"],
    ],
}


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


def iter_files(project_dir: pathlib.Path | None) -> list[pathlib.Path]:
    if project_dir is None or not pathlib.Path(project_dir).exists():
        return []
    return [path for path in pathlib.Path(project_dir).rglob("*") if path.is_file()]


def find_by_name(files: list[pathlib.Path], name: str) -> list[pathlib.Path]:
    target = name.lower()
    return [path for path in files if path.name.lower() == target]


def rel_path(path: pathlib.Path, root: pathlib.Path | None = None) -> str:
    try:
        resolved = path.resolve()
        if root:
            return resolved.relative_to(root.resolve()).as_posix()
        return str(resolved)
    except Exception:
        return str(path)


def has_terms(path: pathlib.Path, terms: list[str]) -> bool:
    text = read_text(path).lower()
    return any(term.lower() in text for term in terms)






def valid_delivery_screenshot(path: pathlib.Path) -> bool:
    if "screenshot_blocked" in path.name.lower():
        return False
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return False
    try:
        data = path.read_bytes()
    except Exception:
        return False
    if len(data) < 100:
        return False
    if path.suffix.lower() == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8")
    if path.suffix.lower() == ".webp":
        return data.startswith(b"RIFF") and b"WEBP" in data[:16]
    return False


def valid_final_zip(path: pathlib.Path) -> bool:
    if not path.exists() or path.stat().st_size <= 0:
        return False
    try:
        with zipfile.ZipFile(path) as zf:
            names = {pathlib.PurePosixPath(name).name for name in zf.namelist()}
    except Exception:
        return False
    return {"README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md"}.issubset(names)


def delivery_smoke_passed(project: pathlib.Path | None) -> bool:
    if not project:
        return False
    manifest = read_json(project / "delivery_manifest.json")
    evidence_status = manifest.get("evidence_status", {}) if isinstance(manifest.get("evidence_status"), dict) else {}
    smoke = evidence_status.get("smoke_command", {}) if isinstance(evidence_status.get("smoke_command"), dict) else {}
    if smoke.get("status") == "PASS":
        return True
    report = read_text(project / "TEST_REPORT.md").lower()
    return "commands_run" in report and "exit_code: 0" in report and "status: pass" in report


def planning_doc_quality(path: pathlib.Path, name: str) -> dict[str, Any]:
    text = read_text(path)
    lowered = text.lower()
    blockers: list[str] = []
    if len(text.strip()) < 500:
        blockers.append("too_short")
    if "todo" in lowered:
        blockers.append("todo_present")
    stripped = text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        blockers.append("json_copy_only")
    if stripped.count("\n") < 8:
        blockers.append("not_enough_sections")
    for index, alternatives in enumerate(PLANNING_DOC_QUALITY_TERMS.get(name.lower(), []), start=1):
        if not any(term.lower() in lowered for term in alternatives):
            blockers.append(f"required_topic_{index}_missing")
    return {"status": "PASS" if not blockers else "FAIL", "blockers": blockers, "length": len(text.strip())}

def requirement_dir_from(run_dir: pathlib.Path | None = None, requirement_dir: pathlib.Path | None = None) -> pathlib.Path | None:
    if requirement_dir:
        return pathlib.Path(requirement_dir)
    if run_dir:
        return pathlib.Path(run_dir) / "requirement_decision"
    return None


def validate_requirement_decision(*, run_dir: pathlib.Path | None = None, requirement_dir: pathlib.Path | None = None) -> dict[str, Any]:
    req_dir = requirement_dir_from(run_dir, requirement_dir)
    blockers: list[str] = []
    evidence: list[str] = []
    if req_dir is None:
        return {"status": "FAIL", "blockers": ["requirement_decision_dir_missing"], "evidence": evidence, "metadata": {}}
    for name in REQUIREMENT_FILES:
        path = req_dir / name
        if path.exists() and path.stat().st_size > 0:
            evidence.append(str(path))
        else:
            blockers.append(f"{name}_missing")
    candidates = read_json(req_dir / "candidate_requirements.json")
    raw_candidates = candidates.get("candidates", [])
    if not isinstance(raw_candidates, list) or len(raw_candidates) < 3:
        blockers.append("candidate_requirements_lt_3")
    for candidate in raw_candidates if isinstance(raw_candidates, list) else []:
        if not isinstance(candidate, dict):
            blockers.append("candidate_requirement_invalid")
            continue
        for key in ("customer_value_score", "clarity_score", "delivery_feasibility", "testability_score"):
            if key not in candidate:
                blockers.append(f"candidate_{candidate.get('id', 'unknown')}_{key}_missing")
    scorecard = read_json(req_dir / "requirement_scorecard.json")
    if not scorecard.get("scores"):
        blockers.append("requirement_scorecard_scores_missing")
    selected = read_json(req_dir / "selected_requirement.json")
    selected_id = str(selected.get("selected_requirement_id", "")).strip()
    if not selected_id:
        blockers.append("selected_requirement_missing")
    if not selected.get("mvp_scope"):
        blockers.append("selected_requirement_mvp_scope_missing")
    if not selected.get("non_goals"):
        blockers.append("selected_requirement_non_goals_missing")
    contract = read_json(req_dir / "acceptance_contract.json")
    if contract.get("contract_id") != "requirement_acceptance_contract_v1":
        blockers.append("acceptance_contract_id_invalid")
    for key in ("required_requirement_artifacts", "status_layers", "forbidden_shortcuts"):
        if not isinstance(contract.get(key), list) or not contract.get(key):
            blockers.append(f"acceptance_contract_{key}_missing")
    return {
        "status": "PASS" if not blockers else ("PARTIAL" if evidence else "FAIL"),
        "blockers": blockers,
        "evidence": evidence,
        "metadata": {
            "requirement_dir": str(req_dir),
            "selected_requirement_id": selected_id,
            "candidate_count": len(raw_candidates) if isinstance(raw_candidates, list) else 0,
        },
    }


def evaluate_planning_contract_gate(
    files: list[pathlib.Path],
    *,
    project_dir: pathlib.Path | None = None,
    run_dir: pathlib.Path | None = None,
    discovery_dir: pathlib.Path | None = None,
    acceptance_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract_docs = []
    if isinstance(acceptance_contract, dict):
        raw_docs = acceptance_contract.get("required_planning_docs", [])
        if isinstance(raw_docs, list):
            contract_docs = [str(item) for item in raw_docs if str(item).strip()]
    required_docs = contract_docs or ["product_brief.md", "technical_plan.md", "interaction_design.md", "acceptance_matrix.md"]
    present: dict[str, list[str]] = {}
    quality: dict[str, Any] = {}
    missing: list[str] = []
    for name in required_docs:
        matches = find_by_name(files, name)
        if matches:
            present[name] = [rel_path(path, project_dir) for path in matches]
            quality[name] = [planning_doc_quality(path, name) for path in matches]
            if not any(item.get("status") == "PASS" for item in quality[name]):
                missing.append(f"{name}_quality_failed")
        else:
            missing.append(f"{name}_missing")

    complexity_contract = None
    if discovery_dir:
        complexity_contract = pathlib.Path(discovery_dir) / "complexity_project_contract.json"
    elif run_dir:
        complexity_contract = pathlib.Path(run_dir) / "discovery" / "complexity_project_contract.json"
    complexity_contract_evidence: list[str] = []
    if complexity_contract and complexity_contract.exists():
        complexity_contract_evidence.append(str(complexity_contract))
    else:
        missing.append("complexity_project_contract.json_missing")

    evidence = [item for paths in present.values() for item in paths] + complexity_contract_evidence
    return {
        "status": "PASS" if not missing else ("PARTIAL" if evidence else "FAIL"),
        "required": required_docs + ["complexity_project_contract.json"],
        "present": present,
        "quality": quality,
        "missing": missing,
        "evidence": evidence,
        "complexity_project_contract": str(complexity_contract) if complexity_contract else "",
    }


def evaluate_layers(
    *,
    project_dir: pathlib.Path | None = None,
    run_dir: pathlib.Path | None = None,
    requirement_dir: pathlib.Path | None = None,
    discovery_dir: pathlib.Path | None = None,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir) if project_dir else None
    run = pathlib.Path(run_dir) if run_dir else None
    files = iter_files(project)
    evidence: list[str] = []
    gaps: list[str] = []

    req = validate_requirement_decision(run_dir=run, requirement_dir=requirement_dir)
    requirement_status = req["status"]
    evidence.extend(req.get("evidence", []))
    gaps.extend(req.get("blockers", []))

    complexity_contract = None
    if discovery_dir:
        complexity_contract = pathlib.Path(discovery_dir) / "complexity_project_contract.json"
    elif run:
        complexity_contract = run / "discovery" / "complexity_project_contract.json"

    req_dir = requirement_dir_from(run, requirement_dir)
    acceptance_contract = read_json(req_dir / "acceptance_contract.json") if req_dir else {}
    planning_gate = evaluate_planning_contract_gate(
        files,
        project_dir=project,
        run_dir=run,
        discovery_dir=discovery_dir,
        acceptance_contract=acceptance_contract,
    )
    product_missing = list(planning_gate.get("missing", []))
    product_contract_status = str(planning_gate.get("status", "FAIL"))
    gaps.extend(product_missing)

    core_missing: list[str] = []
    orchestrator = find_by_name(files, "orchestrator.py")
    stages = find_by_name(files, "stages.py")
    if not orchestrator:
        core_missing.append("orchestrator.py_missing")
    if not stages:
        core_missing.append("stages.py_missing")
    cli = [
        path
        for path in files
        if path.suffix == ".py" and ("cli" in path.name.lower() or path.name.lower() in {"main.py", "__main__.py"}) and has_terms(path, ["argparse", "click", "typer", "__main__"])
    ]
    gui = [
        path
        for path in files
        if path.suffix == ".py" and ("gui" in path.name.lower() or "app" in path.name.lower() or "ui" in path.name.lower()) and has_terms(path, ["tkinter", "streamlit", "gradio", "flask", "fastapi", "pyqt", "pyside"])
    ]
    if not cli:
        core_missing.append("cli_entry_missing")
    if not gui:
        core_missing.append("gui_entry_missing")
    if not (orchestrator and stages and any(has_terms(path, ["orchestrator", "stages"]) for path in cli) and any(has_terms(path, ["orchestrator", "stages"]) for path in gui)):
        core_missing.append("gui_cli_shared_core_missing")
    if product_missing:
        core_missing.append("planning_contract_incomplete")
    stage_schema_result: dict[str, Any] = {}
    if project and complexity_contract and complexity_contract.exists():
        contract = read_json(complexity_contract)
        required_artifacts = contract.get("required_stage_artifacts", [])
        if isinstance(required_artifacts, list) and required_artifacts:
            stage_schema_result = stage_artifact_schema_checker.check(project, [str(item) for item in required_artifacts])
            if stage_schema_result.get("status") != "PASS":
                core_missing.extend(str(item) for item in stage_schema_result.get("blockers", []))
    implementation_status = "PASS" if not core_missing else ("PARTIAL" if orchestrator or stages or cli or gui else "FAIL")
    gaps.extend(core_missing)

    delivery_missing: list[str] = []
    for name in ("README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md"):
        if not find_by_name(files, name):
            delivery_missing.append(f"{name}_missing")
    if run is None or not run.exists():
        delivery_missing.append("run_dir_missing")
    screenshot = any("screenshot" in path.as_posix().lower() and valid_delivery_screenshot(path) for path in files)
    if not screenshot:
        delivery_missing.append("screenshot_missing")
    final_zip = bool(project and valid_final_zip(project / "final_project_bundle.zip"))
    if not final_zip:
        delivery_missing.append("final_project_bundle.zip_missing")
    if not delivery_smoke_passed(project):
        delivery_missing.append("smoke_command_failed")
    if product_missing:
        delivery_missing.append("planning_contract_incomplete")
    delivery_status = "PASS" if not delivery_missing else "NEEDS_REWORK"
    gaps.extend(delivery_missing)

    if delivery_status != "PASS":
        overall_status = "NEEDS_REWORK"
    elif implementation_status != "PASS" or product_contract_status not in {"PASS", "PARTIAL"} or requirement_status == "FAIL":
        overall_status = "FAIL"
    elif product_contract_status == "PARTIAL" or implementation_status == "PARTIAL" or requirement_status == "PARTIAL":
        overall_status = "PARTIAL"
    else:
        overall_status = "PASS"

    return {
        "requirement_decision_status": requirement_status,
        "product_contract_status": product_contract_status,
        "implementation_status": implementation_status,
        "delivery_status": delivery_status,
        "overall_status": overall_status,
        "reason": "layered_acceptance_evaluated",
        "evidence": evidence,
        "known_gaps": gaps,
        "checks": {
            "requirement_decision": req,
            "planning_contract_gate": planning_gate,
            "product_contract_missing": product_missing,
            "implementation_missing": core_missing,
            "stage_artifact_schema": stage_schema_result,
            "delivery_missing": delivery_missing,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", default="")
    parser.add_argument("--run-dir", default="")
    parser.add_argument("--requirement-dir", default="")
    parser.add_argument("--discovery-dir", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = evaluate_layers(
        project_dir=pathlib.Path(args.project_dir) if args.project_dir else None,
        run_dir=pathlib.Path(args.run_dir) if args.run_dir else None,
        requirement_dir=pathlib.Path(args.requirement_dir) if args.requirement_dir else None,
        discovery_dir=pathlib.Path(args.discovery_dir) if args.discovery_dir else None,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"REQUIREMENT_ACCEPTANCE: {result['overall_status']}")
        for gap in result.get("known_gaps", []):
            print(f"- {gap}")
    return 0 if result["overall_status"] in {"PASS", "PARTIAL"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
