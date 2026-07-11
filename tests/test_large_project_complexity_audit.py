from __future__ import annotations

import json
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import large_project_complexity_audit


def make_project(root: pathlib.Path, *, omit: set[str] | None = None) -> pathlib.Path:
    omit = omit or set()
    project = root / "final_project"
    project.mkdir()
    modules = [
        ("dashboard", "Dashboard / Production Overview"),
        ("milestones", "Projects / Milestones"),
        ("asset_library", "Asset Library"),
        ("task_board", "Task Board"),
        ("bug_tracker", "Bug Tracker"),
        ("release_center", "Build & Release Center"),
        ("docs", "Docs / Knowledge Base"),
        ("team_roles", "Team / Roles"),
        ("settings", "Settings"),
    ]
    filtered = [(key, label) for key, label in modules if key not in omit]
    (project / "README.md").write_text(" ".join(label for _key, label in filtered), encoding="utf-8")
    (project / "index.html").write_text(" ".join(label for _key, label in filtered), encoding="utf-8")
    (project / "page_map.json").write_text(json.dumps({"pages": [{"id": key, "name": label} for key, label in filtered]}), encoding="utf-8")
    (project / "feature_matrix.json").write_text(json.dumps({"modules": [{"id": key, "name": label, "features": [key]} for key, label in filtered]}), encoding="utf-8")
    (project / "acceptance_matrix.json").write_text(json.dumps({"expected_features": [key for key, _label in filtered]}), encoding="utf-8")
    demo = project / "demo_data" / "demo.json"
    demo.parent.mkdir()
    demo.write_text('{"assets":[1],"bugs":[1],"builds":[1]}', encoding="utf-8")
    shot = project / "artifacts" / "screenshots" / "overview.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"png")
    bundle = project / "final_project_bundle.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.write(project / "README.md", "README.md")
        zf.write(project / "index.html", "index.html")
    (project / "delivery_manifest.json").write_text(json.dumps({"screenshot_path": str(shot), "package_path": str(bundle)}), encoding="utf-8")
    return project


def test_large_project_complexity_audit_passes_complete_project(tmp_path: pathlib.Path) -> None:
    project = make_project(tmp_path)

    report = large_project_complexity_audit.audit_large_project(project)

    assert report["status"] == "pass"
    assert report["page_count"] >= 8
    assert report["module_count"] >= 6
    assert report["detected_modules"]["asset_library"] is True
    assert report["detected_modules"]["release_center"] is True


def test_complexity_insufficient_project_fails(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "small"
    project.mkdir()
    (project / "README.md").write_text("Dashboard tasks", encoding="utf-8")
    (project / "page_map.json").write_text('{"pages":[{"id":"dashboard"},{"id":"tasks"}]}', encoding="utf-8")
    (project / "feature_matrix.json").write_text('{"modules":[{"id":"dashboard"}]}', encoding="utf-8")

    report = large_project_complexity_audit.audit_large_project(project)

    assert report["status"] != "pass"
    assert report["reason"] == "insufficient_complexity"


def test_missing_large_project_modules_are_real_product_features(tmp_path: pathlib.Path) -> None:
    project = make_project(tmp_path, omit={"asset_library", "release_center"})

    report = large_project_complexity_audit.audit_large_project(project)

    assert "asset_library" in report["missing_core_features"]
    assert "release_center" in report["missing_core_features"]
    assert "commercial" not in report["missing_core_features"]
    assert "readiness" not in report["missing_core_features"]
