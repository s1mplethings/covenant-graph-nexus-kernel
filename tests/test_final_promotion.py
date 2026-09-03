from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.artifact_integrity as artifact_integrity
import scripts.final_delivery_truth as final_delivery_truth
import scripts.formal_model_contract as formal_model_contract
import scripts.final_promotion as final_promotion
import codex_conversation as bridge


def nonblank_png() -> bytes:
    import binascii
    import struct
    import zlib

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)

    width = 640
    height = 360
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row.extend(((x * 3) % 255, (y * 5) % 255, ((x + y) * 2) % 255))
        rows.append(b"\x00" + bytes(row))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")


def make_candidate(root: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    candidate = root / "candidate"
    run_dir = root / "run"
    candidate.mkdir()
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "agent_usage").mkdir(parents=True)
    formal_model_contract.append_model_call(
        run_dir,
        stage="planning",
        provider="local_model_router",
        model="qwen2.5:7b-instruct",
        requested=True,
        executed=True,
        status="ok",
        used_in_formal_chain=True,
        input_value="plan",
        output_value="ok",
    )
    (run_dir / "agent_usage" / "usage_plan.json").write_text(
        json.dumps({"requires_model": True, "uses_model": True, "formal_chain_bound": True}),
        encoding="utf-8",
    )
    (candidate / "_CGNK_CANDIDATE_ONLY_DO_NOT_DELIVER.json").write_text("{}", encoding="utf-8")
    (candidate / "README.md").write_text("# Candidate\n\nRun with `npm test` or open `index.html`.\n", encoding="utf-8")
    (candidate / "DELIVERY_NOTES.md").write_text("# DELIVERY_NOTES\n", encoding="utf-8")
    (candidate / "TEST_REPORT.md").write_text(
        "# TEST_REPORT\n\ncommands_run:\n- npm test\n\nexit_code: 0\n\nstdout_summary:\n- ok\n\nstderr_summary:\n- none\n\nverdict: PASS\n",
        encoding="utf-8",
    )
    (candidate / "known_limits.json").write_text("{}", encoding="utf-8")
    (candidate / "repair_plan.json").write_text("{}", encoding="utf-8")
    (candidate / "index.html").write_text("<!doctype html><title>Task Board</title><body>Task Bug Todo Doing Done Open Fixed Add Dashboard</body>", encoding="utf-8")
    (candidate / "package.json").write_text(json.dumps({"type": "module", "scripts": {"test": "node scripts/test.js"}}), encoding="utf-8")
    (candidate / "scripts").mkdir()
    (candidate / "scripts" / "test.js").write_text("console.log('ok')\n", encoding="utf-8")
    shot = candidate / "artifacts" / "screenshots" / "candidate_home.png"
    video = candidate / "artifacts" / "videos" / "candidate_demo.webm"
    shot.parent.mkdir(parents=True)
    video.parent.mkdir(parents=True)
    shot.write_bytes(nonblank_png())
    video.write_bytes(b"\x1a\x45\xdf\xa3" + b"real video bytes" * 300)
    summary = {
        "verdict": "ASK_USER_REVIEW",
        "test_status": "pass",
        "screenshot_paths": [str(shot)],
        "video_requested": True,
        "video_status": "pass",
        "video_path": str(video),
        "video_blocked_path": "",
        "final_delivery": False,
    }
    (candidate / "candidate_review_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    post_build = {
        "status": "pass",
        "test_result": {"status": "pass", "argv": ["npm", "test"]},
        "ui_smoke": {"status": "pass"},
        "screenshots": [str(shot)],
        "video": str(video),
        "video_status": "pass",
        "video_requested": True,
        "video_blocked": "",
        "candidate_review_summary": str(candidate / "candidate_review_summary.json"),
    }
    (run_dir / "artifacts" / "candidate_post_build_finalize.json").write_text(json.dumps(post_build), encoding="utf-8")
    bundle = run_dir / "artifacts" / "candidate_diagnostic_bundle.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        for path in candidate.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(candidate).as_posix())
    return candidate, run_dir, bundle


def patch_video_validation(monkeypatch) -> None:
    monkeypatch.setattr(final_promotion.visual_evidence, "video_file_diagnostics", lambda path: {"valid": pathlib.Path(path).exists(), "duration_seconds": 3.0})


def test_final_promotion_requires_runnable_candidate_not_review_bundle(monkeypatch) -> None:
    patch_video_validation(monkeypatch)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        candidate, run_dir, bundle = make_candidate(root)

        ready = final_promotion.evaluate_candidate_for_final_promotion(bundle, run_dir=run_dir, candidate_bundle=bundle)

    assert ready["status"] == "fail"
    assert "candidate_project_dir_missing" in ready["blockers"]


def test_final_promotion_rejects_incomplete_canonical_evidence(monkeypatch) -> None:
    patch_video_validation(monkeypatch)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        candidate, run_dir, bundle = make_candidate(root)

        result = final_promotion.promote_candidate_to_final(candidate, run_dir=run_dir, candidate_bundle=bundle)
        final_bundle = pathlib.Path(result["metadata"]["final_project_bundle"])
        assert not final_bundle.exists()

    assert result["status"] == "fail"
    assert result["verdict"] == "FINAL_PROMOTION_REJECTED"
    assert final_bundle.name == "final_project_bundle.zip"
    assert final_bundle != bundle


def test_delivery_manifest_generated_only_after_local_packager_success(monkeypatch) -> None:
    patch_video_validation(monkeypatch)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        candidate, run_dir, bundle = make_candidate(root)

        def fail_packager(*args, **kwargs):
            raise RuntimeError("packager failed")

        monkeypatch.setattr(final_promotion.local_packager, "package_project", fail_packager)
        result = final_promotion.promote_candidate_to_final(candidate, run_dir=run_dir, candidate_bundle=bundle, final_dir=root / "final")

    assert result["status"] == "fail"
    assert result["verdict"] == "local_packager_failed"
    assert not (root / "final" / "delivery_manifest.json").exists()


def test_public_final_gate_rejects_fixture_without_canonical_runtime_and_test_evidence(monkeypatch) -> None:
    patch_video_validation(monkeypatch)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        candidate, run_dir, bundle = make_candidate(root)
        result = final_promotion.promote_candidate_to_final(candidate, run_dir=run_dir, candidate_bundle=bundle)

    gate = result["metadata"]["public_final_gate"]
    assert gate["delivery_allowed"] is False
    assert result["verdict"] == "FINAL_PROMOTION_REJECTED"


def test_public_final_gate_rejects_candidate_bundle_even_if_video_pass(monkeypatch) -> None:
    patch_video_validation(monkeypatch)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        candidate, run_dir, bundle = make_candidate(root)
        manifest = {"package_path": str(bundle), "quality_evidence": {"test_report_found": True, "test_report_has_commands": True, "test_report_has_no_test_executed": False}}
        session = {"messages": [{"role": "user", "text": "screenshot video"}]}
        gate = bridge.evaluate_public_delivery_gate(candidate, manifest, session, phase="final")

    assert gate["delivery_allowed"] is False
    assert gate["can_send_artifacts"] == []
    assert "production_candidate_provenance" in gate[
        "canonical_evidence_gate"
    ]["failures"]


def test_pass_final_requires_final_zip_and_manifest() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir)
        (project / "README.md").write_text("# Project\n", encoding="utf-8")
        result = final_delivery_truth.evaluate(project, {}, {"messages": [{"role": "user", "text": "screenshot video"}]}, phase="final")

    assert result["status"] == "fail"
    assert result["verdict"] == "final_delivery_rejected"


def test_provider_generated_final_zip_is_rejected(monkeypatch) -> None:
    patch_video_validation(monkeypatch)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        candidate, run_dir, bundle = make_candidate(root)
        (candidate / "final_project_bundle.zip").write_bytes(b"provider zip")
        ready = final_promotion.evaluate_candidate_for_final_promotion(candidate, run_dir=run_dir, candidate_bundle=bundle)

    assert ready["status"] == "fail"
    assert "candidate_contains_final_project_bundle.zip" in ready["blockers"]


def test_incomplete_fixture_does_not_produce_final_package(monkeypatch) -> None:
    patch_video_validation(monkeypatch)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = pathlib.Path(temp_dir)
        candidate, run_dir, bundle = make_candidate(root)
        result = final_promotion.promote_candidate_to_final(candidate, run_dir=run_dir, candidate_bundle=bundle)
        final_bundle = pathlib.Path(result["metadata"]["final_project_bundle"])
        integrity = artifact_integrity.validate_final_package(pathlib.Path(result["metadata"]["final_project_dir"]), final_bundle, pathlib.Path(result["metadata"]["delivery_manifest"]))

    assert not final_bundle.exists()
    assert integrity["status"] == "fail"
    assert "missing real final_project_bundle.zip" in integrity["blockers"]
