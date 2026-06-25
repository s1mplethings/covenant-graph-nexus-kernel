#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any


REQUIRED_FIELDS = ["stage", "status", "count", "input_path", "output_path", "created_at", "upstream_artifacts", "items"]


def read_json(path: pathlib.Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def validate_artifact(path: pathlib.Path) -> dict[str, Any]:
    doc = read_json(path)
    if not isinstance(doc, dict):
        return {"path": str(path), "status": "FAIL", "missing": ["json_object"]}
    missing = [field for field in REQUIRED_FIELDS if field not in doc]
    if "upstream_artifacts" in doc and not isinstance(doc.get("upstream_artifacts"), list):
        missing.append("upstream_artifacts_list")
    if "items" in doc and not isinstance(doc.get("items"), list):
        missing.append("items_list")
    return {"path": str(path), "status": "PASS" if not missing else "FAIL", "missing": missing}


def candidate_files(project_dir: pathlib.Path) -> list[pathlib.Path]:
    if not project_dir.exists():
        return []
    return [
        path
        for path in project_dir.rglob("*.json")
        if path.is_file() and path.name not in {"package.json", "delivery_manifest.json", "acceptance_contract.json"}
    ]


def check(project_dir: pathlib.Path, required: list[str] | None = None) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    required_names = [name for name in (required or []) if name]
    files = candidate_files(project)
    by_name = {path.name: path for path in files}
    results: list[dict[str, Any]] = []
    blockers: list[str] = []
    targets: list[pathlib.Path]
    if required_names:
        targets = []
        for name in required_names:
            path = by_name.get(name)
            if path is None:
                blockers.append(f"stage_artifact_missing:{name}")
            else:
                targets.append(path)
    else:
        targets = files
    for path in targets:
        result = validate_artifact(path)
        results.append(result)
        if result["status"] != "PASS":
            blockers.append(f"stage_artifact_schema_invalid:{path.name}")
    return {
        "status": "PASS" if not blockers and bool(targets) else "FAIL",
        "blockers": blockers or ([] if targets else ["stage_artifacts_missing"]),
        "artifacts_checked": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--required", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    required = [item.strip() for item in args.required.split(",") if item.strip()]
    result = check(pathlib.Path(args.project_dir), required)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"CGKN_STAGE_ARTIFACT_SCHEMA: {result['status']}")
        for blocker in result["blockers"]:
            print(f"- {blocker}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
