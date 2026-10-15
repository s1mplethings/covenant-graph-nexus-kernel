from __future__ import annotations

import json
import pathlib
import binascii
import struct
import sys
import zipfile
import zlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import artifact_integrity


def _nonblank_png() -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    width, height = 16, 16
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = []
    for y in range(height):
        pixels = b"".join(
            bytes((20, 20, 20) if x < 8 and y < 8 else (255, 255, 255))
            for x in range(width)
        )
        rows.append(b"\x00" + pixels)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")


def test_final_package_integrity_requires_real_final_bundle_and_manifest(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    for name in ("README.md", "TEST_REPORT.md", "DELIVERY_NOTES.md"):
        (project / name).write_text(name, encoding="utf-8")
    screenshot = project / "screenshot.png"
    screenshot.write_bytes(_nonblank_png())
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


def test_candidate_bundle_requires_video_when_requested(tmp_path: pathlib.Path) -> None:
    bundle = tmp_path / "candidate_diagnostic_bundle.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("candidate_review_summary.json", "{}")
        zf.writestr("TEST_REPORT.md", "commands_run: pytest")
        zf.writestr("known_limits.json", "[]")
        zf.writestr("repair_plan.json", "{}")
        zf.writestr("screenshot_blocked.json", "{}")

    result = artifact_integrity.validate_candidate_bundle(bundle, require_video=True)

    assert result["status"] == "fail"
    assert "candidate bundle missing video or video_blocked" in result["blockers"]


def test_candidate_bundle_with_requested_video_blocked_is_warning_not_full_pass(tmp_path: pathlib.Path) -> None:
    bundle = tmp_path / "candidate_diagnostic_bundle.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("candidate_review_summary.json", "{}")
        zf.writestr("TEST_REPORT.md", "commands_run: pytest")
        zf.writestr("known_limits.json", "[]")
        zf.writestr("repair_plan.json", "{}")
        zf.writestr("screenshot_blocked.json", "{}")
        zf.writestr("video_blocked.json", "{}")

    result = artifact_integrity.validate_candidate_bundle(bundle, require_video=True)

    assert result["status"] == "warning"
    assert "candidate bundle video blocked" in result["warnings"]
    assert not result["blockers"]


def test_candidate_bundle_does_not_require_video_unless_requested(tmp_path: pathlib.Path) -> None:
    bundle = tmp_path / "candidate_diagnostic_bundle.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("candidate_review_summary.json", "{}")
        zf.writestr("TEST_REPORT.md", "commands_run: pytest")
        zf.writestr("known_limits.json", "[]")
        zf.writestr("repair_plan.json", "{}")
        zf.writestr("screenshot_blocked.json", "{}")

    result = artifact_integrity.validate_candidate_bundle(bundle)

    assert result["status"] == "pass"
    assert "candidate bundle missing video or video_blocked" not in result["blockers"]


def test_candidate_bundle_still_requires_non_video_evidence(tmp_path: pathlib.Path) -> None:
    bundle = tmp_path / "candidate_diagnostic_bundle.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("candidate_review_summary.json", "{}")
        zf.writestr("known_limits.json", "[]")
        zf.writestr("repair_plan.json", "{}")

    result = artifact_integrity.validate_candidate_bundle(bundle)

    assert result["status"] == "fail"
    assert "candidate bundle missing TEST_REPORT.md" in result["blockers"]
    assert "candidate bundle missing screenshot or screenshot_blocked" in result["blockers"]
    assert "candidate bundle missing video or video_blocked" not in result["blockers"]
