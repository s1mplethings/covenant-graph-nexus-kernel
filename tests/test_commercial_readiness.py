from __future__ import annotations

import pathlib
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import formal_model_contract, product_acceptance, run_commercial_readiness


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
            row.extend((20, 20, 20) if x < 220 and y < 140 else (255, 255, 255))
        rows.append(b"\x00" + bytes(row))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b"")


def make_project(root: pathlib.Path) -> pathlib.Path:
    project = root / "candidate"
    project.mkdir()
    (project / "README.md").write_text("# commercial readiness project\n", encoding="utf-8")
    (project / "TEST_REPORT.md").write_text("commands_run:\n- npm test\n", encoding="utf-8")
    (project / "package.json").write_text("{}", encoding="utf-8")
    return project


def add_final_delivery_evidence(project: pathlib.Path) -> dict:
    shot = project / "artifacts" / "screenshots" / "candidate_home.png"
    video = project / "artifacts" / "videos" / "candidate_demo.webm"
    shot.parent.mkdir(parents=True, exist_ok=True)
    video.parent.mkdir(parents=True, exist_ok=True)
    shot.write_bytes(nonblank_png())
    video.write_bytes(b"\x1a\x45\xdf\xa3" + b"video bytes" * 300)
    (project / "DELIVERY_NOTES.md").write_text("# DELIVERY_NOTES\n", encoding="utf-8")
    bundle = project / "final_project_bundle.zip"
    manifest = project / "delivery_manifest.json"
    with zipfile.ZipFile(bundle, "w") as zf:
        for path in sorted(project.rglob("*")):
            if path.is_file() and path.name not in {"final_project_bundle.zip", "delivery_manifest.json"}:
                zf.write(path, path.relative_to(project).as_posix())
    manifest.write_text(
        '{"package_path": "' + str(bundle).replace("\\", "\\\\") + '", "screenshot_path": "' + str(shot).replace("\\", "\\\\") + '", "video_path": "' + str(video).replace("\\", "\\\\") + '"}\n',
        encoding="utf-8",
    )
    return {
        "project_dir": str(project),
        "final_project_bundle": str(bundle),
        "delivery_manifest": str(manifest),
        "screenshot_path": str(shot),
        "video_path": str(video),
        "final_delivery_truth": {"metadata": {"delivery_allowed": True, "public_final_gate": {"delivery_allowed": True, "missing": []}}},
        "delivery_allowed": True,
    }


def ok_config() -> dict:
    return {"providers": [{"name": "primary", "models": {"large": "large"}, "quota_required": False, "connectivity_report": "__missing_connectivity_report__.json"}]}


def quota_config() -> dict:
    return {"providers": [{"name": "primary", "models": {"large": "large"}, "quota_required": True}]}


def make_task_board_project(project: pathlib.Path) -> pathlib.Path:
    project.mkdir(parents=True, exist_ok=True)
    (project / "README.md").write_text(
        "# Task Board\n\nAdd, edit, delete, save, and move tasks across Todo, Doing, and Done. Uses localStorage and seed data.\n",
        encoding="utf-8",
    )
    (project / "index.html").write_text(
        "<header><form id='task-form'><select><option>Todo</option><option>Doing</option><option>Done</option></select><button>Add</button></form></header>",
        encoding="utf-8",
    )
    (project / "app-core.js").write_text(
        "const seedTasks=[]; localStorage.setItem('tasks','[]'); function add(){} function edit(){} function deleteTask(){} function move(){} function save(){}",
        encoding="utf-8",
    )
    (project / "app.js").write_text("import './app-core.js';\n", encoding="utf-8")
    (project / "TEST_REPORT.md").write_text("commands_run:\n- npm test\n", encoding="utf-8")
    (project / "package.json").write_text('{"scripts":{"test":"node tests/task-board.test.js"}}', encoding="utf-8")
    (project / "page_map.json").write_text('{"pages":[{"name":"Task Board","features":["add task","edit task","delete task","move task"]}]}', encoding="utf-8")
    shot = project / "artifacts" / "screenshots" / "candidate_home.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    shot.write_bytes(nonblank_png())
    return project


def test_commercial_readiness_ready_when_all_pass(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = pathlib.Path(temp_dir)
        project = make_project(temp_root)
        run_dir = temp_root / "run"
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

        monkeypatch.setattr(run_commercial_readiness.check_test_environment, "check_environment", lambda candidate: {"status": "pass"})
        monkeypatch.setattr(run_commercial_readiness.product_acceptance, "evaluate_product_acceptance", lambda *args, **kwargs: {"status": "pass", "commercial_ready": True, "weak_features": [], "missing_core_features": []})
        monkeypatch.setattr(run_commercial_readiness.artifact_integrity, "scan_no_fake_pass", lambda root: {"status": "pass", "blockers": []})
        monkeypatch.setattr(run_commercial_readiness.formal_delivery_evidence.visual_evidence, "video_file_diagnostics", lambda path: {"valid": pathlib.Path(path).exists(), "reason": "ok"})
        delivery = add_final_delivery_evidence(project)
        report = run_commercial_readiness.assess_commercial_readiness(
            provider_config=ok_config(),
            candidate_dir=project,
            run_live=False,
            run_pytest=False,
            formal_project_result={
                "status": "pass",
                "verdict": "PASS_FINAL",
                "run_dir": str(run_dir),
                "agent_usage": {"plan": {"requires_model": True, "uses_model": True}},
                **delivery,
            },
        )

    assert report["commercial_status"] == "COMMERCIAL_READY"


def test_commercial_readiness_beta_when_provider_quota_blocked(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = make_project(pathlib.Path(temp_dir))
        monkeypatch.setenv("CGNK_PROVIDER_PRIMARY_STATUS", "PROVIDER_QUOTA_EXCEEDED")
        monkeypatch.setattr(run_commercial_readiness.check_test_environment, "check_environment", lambda candidate: {"status": "pass"})
        monkeypatch.setattr(run_commercial_readiness.artifact_integrity, "scan_no_fake_pass", lambda root: {"status": "pass", "blockers": []})

        report = run_commercial_readiness.assess_commercial_readiness(provider_config=quota_config(), candidate_dir=project, run_live=False, run_pytest=False)

    assert report["commercial_status"] == "COMMERCIAL_BETA"
    assert report["provider"]["report_status"] == "COMMERCIAL_BETA_PROVIDER_BLOCKED"


def test_commercial_readiness_blocked_when_security_fails(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = make_project(pathlib.Path(temp_dir))
        (project / "package.json").write_text('{"scripts":{"postinstall":"rm -rf .."}}', encoding="utf-8")
        monkeypatch.setattr(run_commercial_readiness.check_test_environment, "check_environment", lambda candidate: {"status": "pass"})
        monkeypatch.setattr(run_commercial_readiness.artifact_integrity, "scan_no_fake_pass", lambda root: {"status": "pass", "blockers": []})

        report = run_commercial_readiness.assess_commercial_readiness(provider_config=ok_config(), candidate_dir=project, run_live=False, run_pytest=False)

    assert report["commercial_status"] == "COMMERCIAL_BLOCKED"
    assert "security_fail" in report["remaining_blockers"]


def test_commercial_readiness_blocked_when_fake_artifact_accepted(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = make_project(pathlib.Path(temp_dir))
        monkeypatch.setattr(run_commercial_readiness.check_test_environment, "check_environment", lambda candidate: {"status": "pass"})
        monkeypatch.setattr(run_commercial_readiness.artifact_integrity, "scan_no_fake_pass", lambda root: {"status": "fail", "blockers": ["fake"]})

        report = run_commercial_readiness.assess_commercial_readiness(provider_config=ok_config(), candidate_dir=project, run_live=False, run_pytest=False)

    assert report["commercial_status"] == "COMMERCIAL_BLOCKED"
    assert "fake_artifact_risk" in report["remaining_blockers"]


def test_commercial_readiness_beta_when_provider_quota_and_no_product_evidence(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        project = pathlib.Path(temp_dir) / "empty_candidate"
        project.mkdir()
        monkeypatch.setenv("CGNK_PROVIDER_PRIMARY_STATUS", "PROVIDER_QUOTA_EXCEEDED")
        monkeypatch.setattr(run_commercial_readiness.check_test_environment, "check_environment", lambda candidate: {"status": "pass"})
        monkeypatch.setattr(run_commercial_readiness.artifact_integrity, "scan_no_fake_pass", lambda root: {"status": "pass", "blockers": []})

        report = run_commercial_readiness.assess_commercial_readiness(provider_config=quota_config(), candidate_dir=project, run_live=False, run_pytest=False)

    assert report["commercial_status"] == "COMMERCIAL_BETA"
    assert "provider_quota" in report["beta_reasons"]
    assert "no_product_evidence" in report["beta_reasons"]
    assert "product_acceptance_not_commercial_ready" not in report["beta_reasons"]
    assert report["product_acceptance"]["status"] == "not_evaluated"
    assert report["product_acceptance"]["reason"] == "NO_PRODUCT_EVIDENCE"
    assert report["customer_status"]["public_status"] == "WAITING_FOR_PROVIDER_QUOTA"


def test_product_acceptance_does_not_extract_internal_readiness_terms(tmp_path: pathlib.Path) -> None:
    project = make_task_board_project(tmp_path / "task_board")

    report = product_acceptance.evaluate_product_acceptance(
        project,
        goal="commercial readiness project",
        screenshot_metadata={"path": str(project / "artifacts" / "screenshots" / "candidate_home.png"), "valid": True},
        ui_smoke_result={"status": "pass"},
    )

    polluted = {"commercial", "readiness", "commercial_ready", "commercial_readiness", "beta", "pass", "fail", "delivery", "gate"}
    assert polluted.isdisjoint(set(report["missing_core_features"]))
    assert report["metadata"]["expected_feature_sources"]["sources"]["user_goal"] == []
    assert polluted.isdisjoint(set(report["metadata"]["expected_feature_sources"]["features"]))
    assert "page_map.json" in report["metadata"]["expected_feature_sources"]["allowed_source_files"]
    assert report["metadata"]["ux_score_inputs"]["screenshot_read"] is True
    assert report["metadata"]["ux_score_inputs"]["page_map_read"] is True
    assert report["ux_score"] >= 60
    assert not any(str(item).startswith("ux:") for item in report["weak_features"])


def test_product_acceptance_low_ux_reports_specific_inputs(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "thin_project"
    project.mkdir()
    (project / "README.md").write_text("# Task Board\n\nA task board.\n", encoding="utf-8")
    (project / "TEST_REPORT.md").write_text("commands_run:\n- npm test\n", encoding="utf-8")

    report = product_acceptance.evaluate_product_acceptance(project, goal="task board")

    assert report["ux_score"] < 60
    assert "low_ux_score" not in report["weak_features"]
    assert any(str(item).startswith("ux:") for item in report["weak_features"])
    assert report["metadata"]["ux_score_inputs"]["screenshot_read"] is False
    assert "screenshot_evidence_not_read" in report["metadata"]["ux_score_inputs"]["ux_defects"]
