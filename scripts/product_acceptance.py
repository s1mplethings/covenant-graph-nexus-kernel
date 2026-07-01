#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
from typing import Any

try:
    import complexity_project_contract_check
    import requirement_acceptance_check
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import complexity_project_contract_check  # type: ignore[no-redef]
    from scripts import requirement_acceptance_check  # type: ignore[no-redef]


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "examples" / "test_results" / "product_acceptance_report.json"
INTERNAL_FEATURE_TERMS = {
    "beta",
    "commercial",
    "commercial-ready",
    "commercial_ready",
    "commercial-readiness",
    "commercial_readiness",
    "delivery",
    "fail",
    "failed",
    "gate",
    "pass",
    "passed",
    "readiness",
    "ready",
    "status",
}
GOAL_STOP_TERMS = {
    "a",
    "an",
    "and",
    "app",
    "application",
    "build",
    "can",
    "for",
    "include",
    "not",
    "project",
    "should",
    "that",
    "the",
    "this",
    "use",
    "with",
    "一个",
    "和",
    "以及",
    "支持",
    "可以",
    "本地",
}


def _read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def _manifest_files(project_dir: pathlib.Path) -> list[str]:
    if not project_dir.exists():
        return []
    return [path.relative_to(project_dir).as_posix() for path in project_dir.rglob("*") if path.is_file()]


def _clean_feature_term(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff .]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _feature_key(value: Any) -> str:
    return _clean_feature_term(value).replace(" ", "_")


def _is_internal_feature_term(value: Any) -> bool:
    clean = _clean_feature_term(value)
    key = clean.replace(" ", "_")
    return clean in INTERNAL_FEATURE_TERMS or key in INTERNAL_FEATURE_TERMS


def _goal_terms(goal: str) -> list[str]:
    terms: list[str] = []
    for raw in re.split(r"[\s,/，.。;；:：()]+", str(goal or "")):
        term = _clean_feature_term(raw)
        if len(term) >= 3 and term not in GOAL_STOP_TERMS and not _is_internal_feature_term(term):
            terms.append(term)
    return list(dict.fromkeys(terms))[:20]


def _existing_screenshots(project: pathlib.Path) -> list[str]:
    if not project.exists():
        return []
    images: list[str] = []
    for path in project.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            rel = path.relative_to(project).as_posix().lower()
            if "screenshot" in rel or "candidate_home" in rel or "preview" in rel:
                images.append(path.relative_to(project).as_posix())
    return images


def _read_allowed_json(project: pathlib.Path, names: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    for name in names:
        path = project / name
        if path.exists():
            doc = _read_json(path)
            if doc:
                docs[name] = doc
    return docs


def _collect_strings(value: Any, *, keys: set[str] | None = None) -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        if value.strip():
            strings.append(value)
    elif isinstance(value, list):
        for item in value:
            strings.extend(_collect_strings(item, keys=keys))
    elif isinstance(value, dict):
        for key, item in value.items():
            if keys is None or str(key) in keys:
                strings.extend(_collect_strings(item, keys=None))
            elif isinstance(item, (dict, list)):
                strings.extend(_collect_strings(item, keys=keys))
    return strings


def _allowed_expected_features(project: pathlib.Path, goal: str, feature_list: list[str] | None) -> dict[str, Any]:
    docs = _read_allowed_json(
        project,
        (
            "project_spec.json",
            "acceptance_matrix.json",
            "feature_matrix.json",
            "page_map.json",
            "benchmark_expected_features.json",
        ),
    )
    sources: dict[str, list[str]] = {}
    if str(goal or "").strip():
        sources["user_goal"] = _goal_terms(goal)
    if feature_list:
        sources["feature_list"] = [_feature_key(item) for item in feature_list if not _is_internal_feature_term(item)]
    feature_keys = {
        "acceptance",
        "acceptance_criteria",
        "core_features",
        "expected_features",
        "feature",
        "features",
        "flows",
        "mvp_features",
        "pages",
        "required_features",
        "user_needs",
        "workflows",
    }
    for name, doc in docs.items():
        extracted = [_feature_key(item) for item in _collect_strings(doc, keys=feature_keys)]
        sources[name] = [item for item in extracted if item and not _is_internal_feature_term(item)]
    ordered: list[str] = []
    for items in sources.values():
        for item in items:
            if item and item not in ordered:
                ordered.append(item)
    return {"features": ordered[:40], "sources": sources, "allowed_source_files": sorted(docs.keys())}


def _project_text_bundle(project: pathlib.Path, files: list[str], readme: str, test_report: str, delivery_notes: str) -> str:
    parts = [readme, test_report, delivery_notes, " ".join(files)]
    for name in ("index.html", "app.js", "app-core.js", "styles.css", "README.md", "TEST_PLAN.md"):
        parts.append(_read_text(project / name))
    return " ".join(parts).lower()


def _feature_present(term: str, searchable: str) -> bool:
    clean = _clean_feature_term(term)
    key = clean.replace(" ", "_")
    variants = {clean, key, key.replace("_", " ")}
    if any(variant and variant in searchable for variant in variants):
        return True
    words = [word for word in clean.split() if len(word) >= 3 and word not in GOAL_STOP_TERMS]
    return bool(words) and all(word in searchable for word in words)


def _ux_score_inputs(
    project: pathlib.Path,
    *,
    files: list[str],
    readme: str,
    test_report: str,
    delivery_notes: str,
    screenshot_metadata: dict[str, Any] | None,
    ui_smoke_result: dict[str, Any] | None,
    known_limits: list[str],
) -> dict[str, Any]:
    text = _project_text_bundle(project, files, readme, test_report, delivery_notes)
    screenshots = _existing_screenshots(project)
    has_screenshot = bool((screenshot_metadata or {}).get("valid") or (screenshot_metadata or {}).get("path") or screenshots)
    page_map_doc = _read_json(project / "page_map.json")
    has_page_map = bool(page_map_doc)
    page_text = _read_text(project / "index.html").lower()
    navigation_terms = ["header", "form", "button", "select", "todo", "doing", "done"]
    navigation_found = [term for term in navigation_terms if term in page_text]
    demo_terms = ["seedtasks", "seed data", "localstorage", "todo", "doing", "done"]
    demo_found = [term for term in demo_terms if term in text]
    core_flow_terms = ["add", "edit", "delete", "move", "save", "task", "status"]
    core_flow_found = [term for term in core_flow_terms if term in text]
    ui_status = str((ui_smoke_result or {}).get("status") or "").lower()
    readme_found = bool(readme.strip())
    score = 35
    if has_screenshot:
        score += 20
    if has_page_map:
        score += 10
    if readme_found:
        score += 10
    if len(navigation_found) >= 4:
        score += 10
    if len(demo_found) >= 3:
        score += 10
    if len(core_flow_found) >= 5:
        score += 15
    if ui_status == "pass":
        score += 10
    if known_limits:
        score -= min(30, len(known_limits) * 10)
    score = max(0, min(100, score))
    defects: list[str] = []
    if not has_screenshot:
        defects.append("screenshot_evidence_not_read")
    if not readme_found:
        defects.append("readme_missing")
    if len(navigation_found) < 4:
        defects.append("navigation_or_page_structure_weak")
    if len(demo_found) < 3:
        defects.append("demo_data_or_persistence_evidence_weak")
    if len(core_flow_found) < 5:
        defects.append("core_flow_evidence_weak")
    if known_limits:
        defects.append("known_limits_present")
    return {
        "score": score,
        "screenshot_read": has_screenshot,
        "screenshot_paths": screenshots,
        "page_map_read": has_page_map,
        "readme_read": readme_found,
        "navigation_terms_found": navigation_found,
        "demo_data_terms_found": demo_found,
        "core_flow_terms_found": core_flow_found,
        "ui_smoke_status": ui_status or "missing",
        "known_limits_count": len(known_limits),
        "ux_defects": defects,
    }


PIPELINE_STAGE_FIELDS = {
    "stage_name",
    "input_schema",
    "output_schema",
    "artifact_path",
    "validation_rule",
    "failure_mode",
    "unit_test",
}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "pass", "passed", "ok"}
    return bool(value)


def _pipeline_stages(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    raw = manifest.get("stages")
    if not isinstance(raw, list) and isinstance(manifest.get("pipeline"), dict):
        raw = manifest["pipeline"].get("stages")
    if not isinstance(raw, list):
        raw = manifest.get("canonical_stages")
    return [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _int_from_doc(doc: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    current: Any = doc
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    try:
        return int(current)
    except Exception:
        return None


def _test_counts(project: pathlib.Path, test_report: str, acceptance: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for section in ("test_counts", "tests", "minimum_tests"):
        raw = acceptance.get(section)
        if isinstance(raw, dict):
            for key in ("unit_tests", "contract_tests", "integration_tests", "total_tests"):
                try:
                    counts[key] = max(counts.get(key, 0), int(raw.get(key, 0) or 0))
                except Exception:
                    pass
    for key in ("unit_tests", "contract_tests", "integration_tests", "total_tests"):
        value = _int_from_doc(acceptance, (key,))
        if value is not None:
            counts[key] = max(counts.get(key, 0), value)

    text = test_report.lower()
    aliases = {
        "unit_tests": (r"unit[_ ]tests?\s*[:=]\s*(\d+)", r"unit\s+tests\s+>=?\s*(\d+)"),
        "contract_tests": (r"contract[_ ]tests?\s*[:=]\s*(\d+)", r"contract\s+tests\s+>=?\s*(\d+)"),
        "integration_tests": (r"integration[_ ]tests?\s*[:=]\s*(\d+)", r"integration\s+tests\s+>=?\s*(\d+)"),
        "total_tests": (r"total[_ ]tests?\s*[:=]\s*(\d+)", r"(\d+)\s+tests\s+passed"),
    }
    for key, patterns in aliases.items():
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                counts[key] = max(counts.get(key, 0), int(match.group(1)))
    if "total_tests" not in counts:
        tests_dir = project / "tests"
        if tests_dir.exists():
            discovered = 0
            for path in tests_dir.rglob("test_*.py"):
                discovered += len(re.findall(r"^\s*def\s+test_", _read_text(path), flags=re.M))
            if discovered:
                counts["total_tests"] = discovered
    if "total_tests" not in counts:
        counts["total_tests"] = counts.get("unit_tests", 0) + counts.get("contract_tests", 0) + counts.get("integration_tests", 0)
    return {
        "unit_tests": counts.get("unit_tests", 0),
        "contract_tests": counts.get("contract_tests", 0),
        "integration_tests": counts.get("integration_tests", 0),
        "total_tests": counts.get("total_tests", 0),
    }


def _pipeline_bool(project: pathlib.Path, acceptance: dict[str, Any], test_report: str, key: str, artifact: pathlib.Path | None = None) -> bool:
    if key in acceptance:
        return _as_bool(acceptance.get(key))
    status_key = key.replace("_passed", "")
    status = acceptance.get(status_key)
    if isinstance(status, dict) and "status" in status:
        return str(status.get("status", "")).lower() == "pass"
    if artifact and artifact.exists():
        doc = _read_json(artifact)
        if not doc:
            return True
        return str(doc.get("status", "pass")).lower() in {"pass", "passed", "ok", "success"}
    return key.replace("_passed", " passed").replace("_", " ") in test_report.lower()


def _evaluate_pipeline_acceptance(project: pathlib.Path, files: list[str], readme: str, test_report: str, features: list[str]) -> dict[str, Any]:
    manifest = _read_json(project / "pipeline_manifest.json")
    acceptance = _read_json(project / "acceptance_matrix.json")
    stages = _pipeline_stages(manifest)
    stage_count = len(stages)
    complete_stages = [stage for stage in stages if PIPELINE_STAGE_FIELDS.issubset(stage.keys())]
    artifact_contracts = [stage for stage in stages if str(stage.get("artifact_path", "")).strip()]
    artifact_contract_count = len(artifact_contracts)
    existing_artifacts = [
        stage
        for stage in artifact_contracts
        if (project / str(stage.get("artifact_path", ""))).exists()
    ]
    required_dirs = ["src/", "tests/", "examples/input/", "examples/output/", "artifacts/"]
    required_files = ["README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md", "pipeline_manifest.json", "acceptance_matrix.json"]
    has_verify = (project / "verify.ps1").exists() or (project / "verify.py").exists()
    present_core = sum(1 for item in required_dirs if (project / item).exists()) + sum(1 for item in required_files if (project / item).exists()) + (1 if has_verify else 0)
    core_total = len(required_dirs) + len(required_files) + 1

    test_counts = _test_counts(project, test_report, acceptance)
    sample_run_passed = _pipeline_bool(project, acceptance, test_report, "sample_run_passed", project / "artifacts" / "run_report.json")
    cold_replay_passed = _pipeline_bool(project, acceptance, test_report, "cold_replay_passed", project / "artifacts" / "cold_replay_report.json")
    verify_script_passed = _pipeline_bool(project, acceptance, test_report, "verify_script_passed")

    stage_coverage_score = round(100 * len(complete_stages) / stage_count) if stage_count else 0
    contract_coverage_score = round(100 * len(existing_artifacts) / artifact_contract_count) if artifact_contract_count else 0
    feature_terms = [
        "input",
        "manifest",
        "metadata",
        "segment",
        "scoring",
        "candidate",
        "export",
        "report",
        "cold replay",
        "verify",
    ]
    searchable = " ".join([readme.lower(), " ".join(files).lower(), " ".join(features)])
    feature_coverage_score = round(100 * sum(1 for term in feature_terms if term in searchable) / len(feature_terms))
    structure_score = round(100 * present_core / core_total)
    test_score = min(100, round(100 * test_counts["total_tests"] / 50))
    product_score = round(
        stage_coverage_score * 0.25
        + contract_coverage_score * 0.2
        + feature_coverage_score * 0.2
        + structure_score * 0.15
        + test_score * 0.1
        + (10 if sample_run_passed and cold_replay_passed and verify_script_passed else 0)
    )

    missing_core_features: list[str] = []
    if stage_count < 8:
        missing_core_features.append("pipeline_stage_count_lt_8")
    if artifact_contract_count < 6:
        missing_core_features.append("artifact_contract_count_lt_6")
    if test_counts["total_tests"] < 50:
        missing_core_features.append("total_tests_lt_50")
    if not sample_run_passed:
        missing_core_features.append("sample_run_not_passed")
    if not cold_replay_passed:
        missing_core_features.append("cold_replay_not_passed")
    if not verify_script_passed:
        missing_core_features.append("verify_script_not_passed")
    if feature_coverage_score < 80:
        missing_core_features.append("feature_coverage_lt_80")
    if stage_count < 8 and artifact_contract_count < 6:
        missing_core_features.insert(0, "not_pipeline_scale_project")

    commercial_ready = (
        stage_count >= 8
        and artifact_contract_count >= 6
        and test_counts["total_tests"] >= 50
        and sample_run_passed
        and cold_replay_passed
        and verify_script_passed
        and feature_coverage_score >= 80
        and product_score >= 75
        and not missing_core_features
    )
    return {
        "status": "pass" if commercial_ready else "fail",
        "pipeline_mode": True,
        "reason": "pipeline_acceptance_passed" if commercial_ready else ("not_pipeline_scale_project" if "not_pipeline_scale_project" in missing_core_features else "pipeline_acceptance_failed"),
        "product_score": product_score,
        "feature_coverage_score": feature_coverage_score,
        "ux_score": None,
        "maintainability_score": structure_score,
        "pipeline_stage_count": stage_count,
        "artifact_contract_count": artifact_contract_count,
        "sample_run_passed": sample_run_passed,
        "cold_replay_passed": cold_replay_passed,
        "verify_script_passed": verify_script_passed,
        "test_count": test_counts["total_tests"],
        "test_counts": test_counts,
        "stage_coverage_score": stage_coverage_score,
        "contract_coverage_score": contract_coverage_score,
        "commercial_ready": commercial_ready,
        "missing_core_features": missing_core_features,
        "weak_features": [] if commercial_ready else missing_core_features,
        "customer_visible_limitations": [],
        "recommendation": "PASS_FINAL" if commercial_ready else "NEEDS_REWORK",
        "metadata": {
            "project_dir": str(project),
            "file_count": len(files),
            "pipeline_manifest_found": bool(manifest),
            "acceptance_matrix_found": bool(acceptance),
            "verify_script_found": has_verify,
            "required_structure_score": structure_score,
        },
    }


def evaluate_product_acceptance(
    project_dir: pathlib.Path,
    *,
    goal: str = "",
    run_dir: pathlib.Path | None = None,
    discovery_dir: pathlib.Path | None = None,
    require_complexity_contract: bool = False,
    generated_file_manifest: list[str] | None = None,
    readme_path: pathlib.Path | None = None,
    test_report_path: pathlib.Path | None = None,
    screenshot_metadata: dict[str, Any] | None = None,
    video_metadata: dict[str, Any] | None = None,
    ui_smoke_result: dict[str, Any] | None = None,
    feature_list: list[str] | None = None,
    known_limits: list[str] | None = None,
    repair_plan: dict[str, Any] | None = None,
    pipeline_mode: bool = False,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    files = generated_file_manifest or _manifest_files(project)
    readme = _read_text(readme_path or (project / "README.md"))
    test_report = _read_text(test_report_path or (project / "TEST_REPORT.md"))
    delivery_notes = _read_text(project / "DELIVERY_NOTES.md")
    known_limits = list(known_limits or [])
    features = [str(item).lower() for item in (feature_list or [])]
    has_screenshot = bool((screenshot_metadata or {}).get("valid") or (screenshot_metadata or {}).get("path"))
    has_video = bool((video_metadata or {}).get("valid") or (video_metadata or {}).get("path"))
    has_ui_smoke = bool((ui_smoke_result or {}).get("status"))
    has_product_files = bool(files or readme.strip() or test_report.strip() or delivery_notes.strip() or features)
    has_any_evidence = bool(has_product_files or has_screenshot or has_video or has_ui_smoke)
    layered_status = requirement_acceptance_check.evaluate_layers(
        project_dir=project,
        run_dir=pathlib.Path(run_dir) if run_dir else None,
        discovery_dir=pathlib.Path(discovery_dir) if discovery_dir else None,
    )
    contract_path = None
    if discovery_dir:
        contract_path = pathlib.Path(discovery_dir) / "complexity_project_contract.json"
    elif run_dir:
        contract_path = pathlib.Path(run_dir) / "discovery" / "complexity_project_contract.json"
    contract_present = bool(contract_path and contract_path.exists())
    if require_complexity_contract or contract_present:
        contract_check = complexity_project_contract_check.validate(
            discovery_dir=pathlib.Path(discovery_dir) if discovery_dir else None,
            run_dir=pathlib.Path(run_dir) if run_dir else None,
            project_dir=project,
        )
        if contract_check.get("status") != "pass":
            return {
                "status": "fail",
                "reason": "complexity_project_contract_check_failed",
                "product_score": 0,
                "feature_coverage_score": 0,
                "ux_score": None,
                "maintainability_score": None,
                "commercial_ready": False,
                "missing_core_features": list(contract_check.get("blockers", [])),
                "weak_features": list(contract_check.get("blockers", [])),
                "customer_visible_limitations": [],
                "recommendation": "NEEDS_REWORK",
                "metadata": {
                    "project_dir": str(project),
                    "file_count": len(files),
                    "complexity_project_contract_check": contract_check,
                },
                **{key: layered_status.get(key) for key in ("requirement_decision_status", "product_contract_status", "implementation_status", "delivery_status", "overall_status")},
                "layered_acceptance": layered_status,
            }

    if not has_product_files:
        return {
            "status": "not_evaluated",
            "reason": "NO_PRODUCT_EVIDENCE",
            "product_score": None,
            "feature_coverage_score": None,
            "ux_score": None,
            "maintainability_score": None,
            "commercial_ready": False,
            "missing_core_features": [],
            "weak_features": [],
            "customer_visible_limitations": [],
            "recommendation": "COMMERCIAL_BETA",
            "metadata": {
                "project_dir": str(project),
                "file_count": len(files),
                "has_readme": bool(readme.strip()),
                "has_test_report": bool(test_report.strip()),
                "has_delivery_notes": bool(delivery_notes.strip()),
                "has_screenshot_metadata": has_screenshot,
                "has_video_metadata": has_video,
                "has_ui_smoke": has_ui_smoke,
                "has_any_evidence": has_any_evidence,
            },
            **{key: layered_status.get(key) for key in ("requirement_decision_status", "product_contract_status", "implementation_status", "delivery_status", "overall_status")},
            "layered_acceptance": layered_status,
        }
    if pipeline_mode:
        report = _evaluate_pipeline_acceptance(project, files, readme, test_report, features)
        report.update({key: layered_status.get(key) for key in ("requirement_decision_status", "product_contract_status", "implementation_status", "delivery_status", "overall_status")})
        report["layered_acceptance"] = layered_status
        return report
    expected = _allowed_expected_features(project, goal, feature_list)
    terms = [str(item) for item in expected.get("features", []) if str(item).strip()]
    searchable = _project_text_bundle(project, files, readme, test_report, delivery_notes)

    missing_core_features = [term for term in terms if not _feature_present(term, searchable) and not _is_internal_feature_term(term)]
    feature_coverage_score = 100 if not terms else round(100 * (len(terms) - len(missing_core_features)) / len(terms))
    if features:
        feature_coverage_score = max(feature_coverage_score, min(100, 55 + len(features) * 8))
    ux_inputs = _ux_score_inputs(
        project,
        files=files,
        readme=readme,
        test_report=test_report,
        delivery_notes=delivery_notes,
        screenshot_metadata=screenshot_metadata,
        ui_smoke_result=ui_smoke_result,
        known_limits=known_limits,
    )
    ux_score = int(ux_inputs["score"])

    maintainability_score = 45
    if any(path.endswith("README.md") for path in files) or readme:
        maintainability_score += 20
    if "commands_run" in test_report or "npm test" in test_report or "pytest" in test_report:
        maintainability_score += 20
    if any(path.endswith(("package.json", "requirements.txt", "pyproject.toml")) for path in files):
        maintainability_score += 10
    if repair_plan and repair_plan.get("status") in {"pass", "done"}:
        maintainability_score += 5
    maintainability_score = min(100, maintainability_score)

    product_score = round(feature_coverage_score * 0.45 + ux_score * 0.3 + maintainability_score * 0.25)
    customer_visible_limitations = [str(item) for item in known_limits if str(item).strip()]
    weak_features: list[str] = []
    if ux_score < 60:
        defects = ux_inputs.get("ux_defects", []) if isinstance(ux_inputs.get("ux_defects", []), list) else []
        if defects:
            weak_features.extend(f"ux:{item}" for item in defects[:8])
        else:
            weak_features.append("ux:evidence_score_below_60")
    if maintainability_score < 60:
        weak_features.append("maintainability_evidence_weak")

    commercial_ready = product_score >= 75 and feature_coverage_score >= 80 and ux_score >= 60 and not missing_core_features
    if missing_core_features:
        status = "fail"
        recommendation = "NEEDS_REWORK"
    elif commercial_ready:
        status = "pass"
        recommendation = "PASS_FINAL"
    elif product_score >= 60:
        status = "warning"
        recommendation = "DELIVER_WITH_WARNINGS"
    else:
        status = "warning"
        recommendation = "ASK_USER_REVIEW"

    report = {
        "status": status,
        "product_score": product_score,
        "feature_coverage_score": feature_coverage_score,
        "ux_score": ux_score,
        "maintainability_score": maintainability_score,
        "commercial_ready": commercial_ready,
        "missing_core_features": missing_core_features,
        "weak_features": weak_features,
        "customer_visible_limitations": customer_visible_limitations,
        "recommendation": recommendation,
        "metadata": {
            "project_dir": str(project),
            "file_count": len(files),
            "video_present": has_video,
            "has_delivery_notes": bool(delivery_notes.strip()),
            "expected_feature_sources": expected,
            "ux_score_inputs": ux_inputs,
        },
    }
    report.update({key: layered_status.get(key) for key in ("requirement_decision_status", "product_contract_status", "implementation_status", "delivery_status", "overall_status")})
    report["layered_acceptance"] = layered_status
    return report


def write_report(path: pathlib.Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--goal", default="")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--pipeline-mode", action="store_true")
    parser.add_argument("--run-dir", default="")
    parser.add_argument("--discovery-dir", default="")
    parser.add_argument("--require-complexity-contract", action="store_true")
    args = parser.parse_args()
    report = evaluate_product_acceptance(
        pathlib.Path(args.project_dir),
        goal=args.goal,
        pipeline_mode=args.pipeline_mode,
        run_dir=pathlib.Path(args.run_dir) if args.run_dir else None,
        discovery_dir=pathlib.Path(args.discovery_dir) if args.discovery_dir else None,
        require_complexity_contract=bool(args.require_complexity_contract),
    )
    write_report(pathlib.Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] != "fail" else 2


if __name__ == "__main__":
    raise SystemExit(main())
