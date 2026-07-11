#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import zipfile
from typing import Any


INTERNAL_TERMS = {"commercial", "readiness", "commercial_ready", "commercial_readiness", "beta", "delivery", "gate"}

REQUIRED_MODULES: dict[str, tuple[str, ...]] = {
    "dashboard": ("dashboard", "overview", "production overview"),
    "asset_library": ("asset library", "asset_library", "assets", "content library"),
    "bug_tracker": ("bug tracker", "bug_tracker", "bugs", "issues"),
    "release_center": ("release center", "release_center", "build", "release", "builds"),
    "docs": ("docs", "knowledge", "knowledge base", "documentation"),
    "settings": ("settings", "team", "roles", "permissions"),
}


def read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def collect_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(collect_strings(item))
        return out
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(collect_strings(item))
        return out
    return []


def page_count_from_page_map(doc: dict[str, Any]) -> int:
    pages = doc.get("pages")
    if isinstance(pages, list):
        return len([item for item in pages if isinstance(item, dict) or str(item).strip()])
    modules = doc.get("modules")
    if isinstance(modules, list):
        return len([item for item in modules if isinstance(item, dict) or str(item).strip()])
    return 0


def module_count_from_feature_matrix(doc: dict[str, Any]) -> int:
    for key in ("modules", "domains", "features"):
        value = doc.get(key)
        if isinstance(value, list):
            return len([item for item in value if isinstance(item, dict) or str(item).strip()])
        if isinstance(value, dict):
            return len(value)
    return 0


def has_zip_candidate_marker(bundle: pathlib.Path) -> bool:
    if not bundle.exists():
        return False
    try:
        with zipfile.ZipFile(bundle) as zf:
            return any(pathlib.PurePosixPath(name).name == "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json" for name in zf.namelist())
    except Exception:
        return False


def evidence_bundle(project: pathlib.Path) -> str:
    docs = [
        read_text(project / "README.md"),
        read_text(project / "index.html"),
        read_text(project / "app.js"),
        read_text(project / "app-core.js"),
        json.dumps(read_json(project / "page_map.json"), ensure_ascii=False),
        json.dumps(read_json(project / "feature_matrix.json"), ensure_ascii=False),
        json.dumps(read_json(project / "acceptance_matrix.json"), ensure_ascii=False),
        json.dumps(read_json(project / "delivery_manifest.json"), ensure_ascii=False),
    ]
    for path in (project / "demo_data").glob("*.json") if (project / "demo_data").exists() else []:
        docs.append(read_text(path))
    return "\n".join(docs).lower().replace("_", " ")


def module_evidence_bundle(project: pathlib.Path) -> str:
    docs = [
        read_text(project / "README.md"),
        read_text(project / "index.html"),
        read_text(project / "app.js"),
        json.dumps(read_json(project / "page_map.json"), ensure_ascii=False),
        json.dumps(read_json(project / "feature_matrix.json"), ensure_ascii=False),
        json.dumps(read_json(project / "acceptance_matrix.json"), ensure_ascii=False),
    ]
    return "\n".join(docs).lower().replace("_", " ")


def audit_large_project(project_dir: str | pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    page_map = read_json(project / "page_map.json")
    feature_matrix = read_json(project / "feature_matrix.json")
    acceptance_matrix = read_json(project / "acceptance_matrix.json")
    manifest = read_json(project / "delivery_manifest.json")
    page_count = page_count_from_page_map(page_map)
    module_count = module_count_from_feature_matrix(feature_matrix)
    text = evidence_bundle(project)
    module_text = module_evidence_bundle(project)
    detected_modules = {
        name: any(term in module_text for term in terms)
        for name, terms in REQUIRED_MODULES.items()
    }
    demo_data_files = list((project / "demo_data").glob("*")) if (project / "demo_data").exists() else []
    screenshot = pathlib.Path(str(manifest.get("screenshot_path") or ""))
    if not screenshot.is_absolute():
        screenshot = project / screenshot
    final_bundle = project / "final_project_bundle.zip"
    checks = {
        "page_count": page_count,
        "module_count": module_count,
        "readme_exists": (project / "README.md").exists(),
        "delivery_manifest_exists": (project / "delivery_manifest.json").exists(),
        "feature_matrix_exists": (project / "feature_matrix.json").exists(),
        "page_map_exists": (project / "page_map.json").exists(),
        "acceptance_matrix_exists": bool(acceptance_matrix),
        "has_demo_data": bool(demo_data_files),
        "screenshot_evidence_exists": screenshot.exists() and screenshot.is_file(),
        "final_project_bundle_exists": final_bundle.exists() and final_bundle.is_file() and final_bundle.stat().st_size > 0,
        "zip_contains_candidate_marker": has_zip_candidate_marker(final_bundle),
        **{f"has_{name}": value for name, value in detected_modules.items()},
    }
    missing_core_features: list[str] = []
    if page_count < 8:
        missing_core_features.append("page_count_lt_8")
    if module_count < 6:
        missing_core_features.append("module_count_lt_6")
    for name, present in detected_modules.items():
        if not present:
            missing_core_features.append(name)
    required_files = {
        "readme": checks["readme_exists"],
        "page_map": checks["page_map_exists"],
        "feature_matrix": checks["feature_matrix_exists"],
        "acceptance_matrix": checks["acceptance_matrix_exists"],
        "demo_data": checks["has_demo_data"],
        "screenshot_evidence": checks["screenshot_evidence_exists"],
        "final_project_bundle": checks["final_project_bundle_exists"],
        "delivery_manifest": checks["delivery_manifest_exists"],
    }
    for name, present in required_files.items():
        if not present:
            missing_core_features.append(name)
    if checks["zip_contains_candidate_marker"]:
        missing_core_features.append("candidate_marker_in_final_zip")
    missing_core_features = [item for item in dict.fromkeys(missing_core_features) if item not in INTERNAL_TERMS]
    status = "pass" if not missing_core_features else "fail"
    reason = "large_project_complexity_passed" if status == "pass" else "insufficient_complexity"
    return {
        "status": status,
        "reason": reason,
        "page_count": page_count,
        "module_count": module_count,
        "detected_modules": detected_modules,
        "missing_core_features": missing_core_features,
        "weak_features": [],
        "checks": checks,
        "metadata": {
            "project_dir": str(project),
            "page_map_entries": page_count,
            "feature_matrix_entries": module_count,
            "demo_data_files": [str(path) for path in demo_data_files],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    report = audit_large_project(pathlib.Path(args.project_dir))
    if args.report:
        path = pathlib.Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
