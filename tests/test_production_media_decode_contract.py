from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import capability_manifest_check
import delivery_evidence_builder
import implementation_structure_materializer
import local_media_adapter
import production_media_decode_contract


def read_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_media_decode_unavailable_when_ffmpeg_missing(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: None)
    project = tmp_path / "project"
    wav = project / "input.wav"
    local_media_adapter.create_tiny_wav(wav)

    result = production_media_decode_contract.run_media_decode(
        project_dir=project,
        input_path=pathlib.Path("input.wav"),
        timeout=0.1,
    )

    assert result["status"] == "unavailable"
    assert result["adapter"] == "none"
    assert result["size"] == 0
    assert "media_decode_unavailable" in result["blockers"]
    assert read_json(project / "media_decode_artifact.json")["status"] == "unavailable"


def test_media_decode_verified_writes_real_output_hash_and_size(tmp_path: pathlib.Path, monkeypatch) -> None:
    project = tmp_path / "project"
    wav = project / "input.wav"
    local_media_adapter.create_tiny_wav(wav)

    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: "fake-ffmpeg" if name == "ffmpeg" else None)

    def fake_run(command: list[str], *, timeout: float = 2.0) -> dict:
        if "-version" in command:
            return {"command": command, "returncode": 0, "duration_seconds": 0.001, "stdout": "ffmpeg fake\n", "stderr": "", "timed_out": False}
        output = pathlib.Path(command[-1])
        local_media_adapter.create_tiny_wav(output, duration_seconds=0.1)
        return {"command": command, "returncode": 0, "duration_seconds": 0.01, "stdout": "", "stderr": "", "timed_out": False}

    monkeypatch.setattr(local_media_adapter, "run_bounded", fake_run)

    result = production_media_decode_contract.run_media_decode(
        project_dir=project,
        input_path=pathlib.Path("input.wav"),
        timeout=0.1,
    )

    output = project / "media_decode_output.wav"
    assert result["status"] == "verified"
    assert output.exists() and output.stat().st_size > 0
    assert result["sha256"] == local_media_adapter.sha256(output)
    assert result["size"] == output.stat().st_size
    assert result["duration_seconds"] > 0


def test_media_decode_empty_output_fails(tmp_path: pathlib.Path, monkeypatch) -> None:
    project = tmp_path / "project"
    wav = project / "input.wav"
    local_media_adapter.create_tiny_wav(wav)
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: "fake-ffmpeg" if name == "ffmpeg" else None)

    def fake_run(command: list[str], *, timeout: float = 2.0) -> dict:
        if "-version" in command:
            return {"command": command, "returncode": 0, "duration_seconds": 0.001, "stdout": "ffmpeg fake\n", "stderr": "", "timed_out": False}
        pathlib.Path(command[-1]).write_bytes(b"")
        return {"command": command, "returncode": 0, "duration_seconds": 0.01, "stdout": "", "stderr": "", "timed_out": False}

    monkeypatch.setattr(local_media_adapter, "run_bounded", fake_run)

    result = production_media_decode_contract.run_media_decode(project_dir=project, input_path=pathlib.Path("input.wav"), timeout=0.1)

    assert result["status"] == "failed"
    assert "media_decode_output_empty_or_missing" in result["blockers"]


def test_media_decode_returncode_and_timeout_fail(tmp_path: pathlib.Path, monkeypatch) -> None:
    project = tmp_path / "project"
    wav = project / "input.wav"
    local_media_adapter.create_tiny_wav(wav)
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: "fake-ffmpeg" if name == "ffmpeg" else None)

    def fake_run(command: list[str], *, timeout: float = 2.0) -> dict:
        if "-version" in command:
            return {"command": command, "returncode": 0, "duration_seconds": 0.001, "stdout": "ffmpeg fake\n", "stderr": "", "timed_out": False}
        return {"command": command, "returncode": None, "duration_seconds": timeout, "stdout": "", "stderr": "", "timed_out": True}

    monkeypatch.setattr(local_media_adapter, "run_bounded", fake_run)

    result = production_media_decode_contract.run_media_decode(project_dir=project, input_path=pathlib.Path("input.wav"), timeout=0.1)

    assert result["status"] == "failed"
    assert result["timed_out"] is True
    assert "media_decode_timeout" in result["blockers"]


def test_capability_manifest_records_media_decode_without_commercial_ready(tmp_path: pathlib.Path, monkeypatch) -> None:
    project = tmp_path / "project"
    user_wav = project / "input.wav"
    local_media_adapter.create_tiny_wav(user_wav)
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: f"fake-{name}" if name in {"ffmpeg", "ffprobe"} else None)

    def fake_run(command: list[str], *, timeout: float = 2.0) -> dict:
        if "-version" in command:
            return {"command": command, "returncode": 0, "duration_seconds": 0.001, "stdout": "ffmpeg fake\n", "stderr": "", "timed_out": False}
        if "ffprobe" in str(command[0]).lower():
            return {"command": command, "returncode": 0, "duration_seconds": 0.001, "stdout": "{}", "stderr": "", "timed_out": False}
        output = pathlib.Path(command[-1])
        local_media_adapter.create_tiny_wav(output, duration_seconds=0.1)
        return {"command": command, "returncode": 0, "duration_seconds": 0.01, "stdout": "", "stderr": "", "timed_out": False}

    monkeypatch.setattr(local_media_adapter, "run_bounded", fake_run)

    manifest = local_media_adapter.build_capability_manifest(project, user_media_path=pathlib.Path("input.wav"), timeout=0.1)
    media_decode = manifest["capabilities"]["media_decode"]

    assert media_decode["status"] == "verified"
    assert media_decode["tool"] == "ffmpeg"
    assert media_decode["size"] > 0
    assert media_decode["sha256"]
    assert media_decode["commercial_ready"] is False
    assert manifest["commercial_ready"] is False
    assert capability_manifest_check.check(project / "capability_manifest.json", project_dir=project)["status"] == "PASS"


def test_delivery_manifest_and_reports_reference_media_decode(tmp_path: pathlib.Path, monkeypatch) -> None:
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

    assert result["status"] == "NEEDS_REWORK"
    delivery_manifest = read_json(project / "delivery_evidence_manifest.json")
    media_decode = delivery_manifest["capability_manifest"]["capabilities"]["media_decode"]
    assert media_decode["status"] in {"verified", "unavailable"}
    assert "media_decode_artifact.json" in delivery_manifest["files"]
    assert "media_decode_status:" in (project / "TEST_REPORT.md").read_text(encoding="utf-8")
    notes = (project / "DELIVERY_NOTES.md").read_text(encoding="utf-8")
    assert "Media decode support is bounded local ffmpeg extract evidence" in notes
    assert delivery_manifest["capability_manifest"]["commercial_ready"] is False
