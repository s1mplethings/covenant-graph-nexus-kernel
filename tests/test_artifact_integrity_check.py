from __future__ import annotations

import json
import pathlib
import sys
import zipfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import artifact_integrity
import delivery_evidence_builder


def test_final_package_integrity_requires_real_final_bundle_and_manifest(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    for name in ("README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md"):
        (project / name).write_text(name, encoding="utf-8")
    screenshot = project / "screenshot.png"
    delivery_evidence_builder.render_status_png(screenshot, {"status": "PASS", "argv": ["pytest"]})
    bundle = project / "final_project_bundle.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        for name in ("README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md", "screenshot.png"):
            zf.write(project / name, name)
        zf.writestr("demo.webm", b"not inspected by this integrity test")
    manifest = project / "delivery_manifest.json"
    manifest.write_text(json.dumps({"package_path": str(bundle)}), encoding="utf-8")

    result = artifact_integrity.validate_final_package(project, bundle, manifest)

    assert result["status"] == "pass"


def test_candidate_bundle_cannot_contain_final_delivery_artifacts(tmp_path: pathlib.Path) -> None:
    bundle = tmp_path / "candidate_diagnostic_bundle.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("candidate_review_summary.json", "{}")
        zf.writestr("TEST_REPORT.md", "commands_run: pytest")
        zf.writestr("known_limits.json", "[]")
        zf.writestr("repair_plan.json", "{}")
        zf.writestr("video_blocked.json", "{}")
        zf.writestr("screenshot_blocked.json", "{}")
        zf.writestr("final_project_bundle.zip", b"fake")

    result = artifact_integrity.validate_candidate_bundle(bundle)

    assert result["status"] == "fail"
    assert any("final_project_bundle.zip" in blocker for blocker in result["blockers"])
