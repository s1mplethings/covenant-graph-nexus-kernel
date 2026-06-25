from __future__ import annotations

import json
import pathlib
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import capability_manifest_check
import delivery_evidence_builder
import implementation_structure_materializer
import local_media_adapter
import user_media_pipeline_contract


def read_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_user_media_contract_accepts_real_wav_and_writes_artifacts(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: None)
    project = tmp_path / "project"
    wav = project / "inputs" / "user_audio.wav"
    local_media_adapter.create_tiny_wav(wav)

    result = user_media_pipeline_contract.prepare_user_media_pipeline(
        project_dir=project,
        input_path=pathlib.Path("inputs/user_audio.wav"),
        output_dir=project,
        timeout=0.1,
    )

    assert result["status"] == "PASS"
    media_manifest = read_json(project / "media_manifest.json")
    assert media_manifest["stage"] == "media_manifest"
    assert media_manifest["status"] == "PASS"
    assert media_manifest["real_user_media_input"] is True
    assert media_manifest["file_type"] == "wav"
    assert media_manifest["size"] == wav.stat().st_size
    assert media_manifest["sha256"] == local_media_adapter.sha256(wav)
    assert media_manifest["metadata_status"] == "python_wave_verified"
    assert media_manifest["items"][0]["sha256"] == local_media_adapter.sha256(wav)
    assert read_json(project / "user_media_inspect.json")["stage"] == "inspect_media"
    assert read_json(project / "user_media_smoke_log.json")["status"] == "PASS"
    assert read_json(project / "user_media_fixture.json")["user_media_contract"] is True


def test_user_media_contract_rejects_non_media_text_file(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: None)
    project = tmp_path / "project"
    bad = project / "notes.txt"
    bad.parent.mkdir(parents=True)
    bad.write_text("not media", encoding="utf-8")

    result = user_media_pipeline_contract.prepare_user_media_pipeline(
        project_dir=project,
        input_path=pathlib.Path("notes.txt"),
        output_dir=project,
        timeout=0.1,
    )

    assert result["status"] == "FAIL"
    assert "unsupported_media_type" in result["blockers"]
    assert read_json(project / "media_manifest.json")["status"] == "FAIL"
    assert not (project / "user_media_fixture.json").exists()


def test_capability_manifest_records_real_user_media_and_detects_tampering(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: None)
    project = tmp_path / "project"
    user_wav = project / "input.wav"
    local_media_adapter.create_tiny_wav(user_wav)

    manifest = local_media_adapter.build_capability_manifest(
        project,
        user_media_path=pathlib.Path("input.wav"),
        timeout=0.1,
    )

    user_media = manifest["capabilities"]["user_media_input"]
    assert user_media["status"] == "verified"
    assert user_media["source"] == "real_user_media_input"
    assert user_media["size"] == user_wav.stat().st_size
    assert user_media["sha256"] == local_media_adapter.sha256(user_wav)
    assert user_media["metadata_status"] == "python_wave_verified"
    assert manifest["commercial_ready"] is False
    assert capability_manifest_check.check(project / "capability_manifest.json", project_dir=project)["status"] == "PASS"

    manifest_path = project / "capability_manifest.json"
    tampered = read_json(manifest_path)
    tampered["capabilities"]["user_media_input"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = capability_manifest_check.check(manifest_path, project_dir=project)
    assert result["status"] == "FAIL"
    assert "user_media_sha256_mismatch" in result["blockers"]


def test_generated_cli_supports_real_user_wav_input(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: None)
    project = tmp_path / "generated_project"
    run_dir = tmp_path / "run"
    implementation_structure_materializer.materialize(project_dir=project, run_dir=run_dir)

    proc = subprocess.run(
        [sys.executable, "cli.py", "--input", "fixtures/sample_audio.wav", "--output-dir", "."],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert proc.returncode == 0, proc.stderr
    manifest = read_json(project / "media_manifest.json")
    assert manifest["real_user_media_input"] is True
    assert manifest["metadata_status"] in {"python_wave_verified", "ffprobe_verified"}
    capability = read_json(project / "capability_manifest.json")
    assert capability["capabilities"]["user_media_input"]["source"] == "real_user_media_input"
    assert capability["capabilities"]["user_media_input"]["metadata_status"] in {"python_wave_verified", "ffprobe_verified"}
    assert capability["capabilities"]["transcription"]["status"] == "placeholder_transcription"
    assert capability["commercial_ready"] is False


def test_delivery_evidence_records_user_media_pipeline_status(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: None)
    project = tmp_path / "generated_project"
    run_dir = tmp_path / "run"
    implementation_structure_materializer.materialize(project_dir=project, run_dir=run_dir)

    result = delivery_evidence_builder.build(
        project_dir=project,
        run_dir=run_dir,
        smoke_command=[sys.executable, "cli.py", "--input", "fixtures/sample_audio.wav", "--output-dir", "."],
        capture_screenshot=True,
    )

    assert result["status"] == "PASS"
    delivery_manifest = read_json(project / "delivery_manifest.json")
    assert delivery_manifest["capability_manifest"]["capabilities"]["user_media_input"]["status"] == "verified"
    assert "media_manifest.json" in delivery_manifest["files"]
    assert "capability_manifest.json" in delivery_manifest["files"]
    assert "user_media_smoke_log.json" in delivery_manifest["files"]
    test_report = (project / "TEST_REPORT.md").read_text(encoding="utf-8")
    delivery_notes = (project / "DELIVERY_NOTES.md").read_text(encoding="utf-8")
    assert "user_media_input_status: verified" in test_report
    assert "User media pipeline support is a bounded local input contract" in delivery_notes
    assert delivery_manifest["capability_manifest"]["commercial_ready"] is False
