from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import capability_manifest_check
import local_media_adapter


def test_capability_manifest_check_accepts_valid_manifest(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: None)
    project = tmp_path / "project"
    manifest = local_media_adapter.build_capability_manifest(project, timeout=0.1)

    result = capability_manifest_check.check(project / "capability_manifest.json", project_dir=project)

    assert manifest["commercial_ready"] is False
    assert result["status"] == "PASS"
    assert result["selected_adapter"] == "python_wave_verified"


def test_capability_manifest_check_fails_when_wav_hash_is_tampered(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: None)
    project = tmp_path / "project"
    local_media_adapter.build_capability_manifest(project, timeout=0.1)
    path = project / "capability_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["capabilities"]["media_fixture"]["sha256"] = "0" * 64
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = capability_manifest_check.check(path, project_dir=project)

    assert result["status"] == "FAIL"
    assert "media_fixture_sha256_mismatch" in result["blockers"]


def test_capability_manifest_check_rejects_transcription_model_claim(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: None)
    project = tmp_path / "project"
    local_media_adapter.build_capability_manifest(project, timeout=0.1)
    path = project / "capability_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["capabilities"]["transcription"]["status"] = "verified"
    manifest["capabilities"]["transcription"]["tool"] = "fake_model"
    manifest["capabilities"]["transcription"]["model"] = "pretend"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = capability_manifest_check.check(path, project_dir=project)

    assert result["status"] == "FAIL"
    assert "transcription_status_invalid" in result["blockers"]
    assert "transcription_claims_real_model" in result["blockers"]


def test_capability_manifest_check_accepts_placeholder_but_not_as_verified(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: None)
    project = tmp_path / "project"
    local_media_adapter.build_capability_manifest(project, timeout=0.1)
    manifest = json.loads((project / "capability_manifest.json").read_text(encoding="utf-8"))

    result = capability_manifest_check.check(project / "capability_manifest.json", project_dir=project)

    assert result["status"] == "PASS"
    assert manifest["capabilities"]["transcription"]["status"] == "placeholder_transcription"
    assert manifest["capabilities"]["transcription"]["model"] is None
    assert manifest["capabilities"]["transcription"]["commercial_ready"] is False
