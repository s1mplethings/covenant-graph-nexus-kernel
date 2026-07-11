from __future__ import annotations

import json
import pathlib
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import capability_manifest_check
import local_media_adapter
import local_model_adapter
import local_transcription_fixture_adapter


def test_fixture_adapter_reads_wav_and_writes_schema(tmp_path: pathlib.Path) -> None:
    wav = tmp_path / "sample_audio.wav"
    output = tmp_path / "transcript.json"
    local_media_adapter.create_tiny_wav(wav)

    transcript = local_transcription_fixture_adapter.build_transcript(wav, output)
    output.write_text(json.dumps(transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    loaded = json.loads(output.read_text(encoding="utf-8"))

    for key in ("stage", "status", "adapter", "input_path", "output_path", "created_at", "segments", "text", "degraded", "evidence"):
        assert key in loaded
    assert loaded["stage"] == "transcription"
    assert loaded["status"] == "verified"
    assert loaded["adapter"] == "local_transcription_fixture_adapter"
    assert loaded["degraded"] is True
    assert loaded["not_production_asr"] is True
    assert "not production ASR" in loaded["text"]


def test_fixture_adapter_cli_generates_transcript_json(tmp_path: pathlib.Path) -> None:
    wav = tmp_path / "sample_audio.wav"
    output = tmp_path / "transcript.json"
    local_media_adapter.create_tiny_wav(wav)

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "local_transcription_fixture_adapter.py"), "--input", str(wav), "--output", str(output)],
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert proc.returncode == 0
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["status"] == "verified"
    assert loaded["not_production_asr"] is True


def test_capability_manifest_uses_fixture_adapter_command(tmp_path: pathlib.Path, monkeypatch) -> None:
    project = tmp_path / "project"
    wav = project / "fixtures" / "sample_audio.wav"
    local_media_adapter.create_tiny_wav(wav)
    command = f'"{sys.executable}" "{ROOT / "scripts" / "local_transcription_fixture_adapter.py"}" --input "{{input}}" --output "{{output}}"'
    monkeypatch.setenv(local_model_adapter.ENV_COMMAND, command)

    manifest = local_media_adapter.build_capability_manifest(project, fixture_path=wav, timeout=2.0)
    transcription = manifest["capabilities"]["transcription"]
    check = capability_manifest_check.check(project / "capability_manifest.json", project_dir=project)

    assert transcription["status"] == "local_model_verified"
    assert transcription["tool"] == "configured_command"
    assert transcription["adapter"] == "local_transcription_fixture_adapter"
    assert transcription["returncode"] == 0
    assert transcription["artifact"]["sha256"]
    assert transcription["artifact"]["size"] > 0
    assert transcription["not_production_asr"] is True
    assert transcription["commercial_ready"] is False
    assert check["status"] == "PASS"


def test_fixture_adapter_command_does_not_make_commercial_ready(tmp_path: pathlib.Path, monkeypatch) -> None:
    project = tmp_path / "project"
    wav = project / "fixtures" / "sample_audio.wav"
    local_media_adapter.create_tiny_wav(wav)
    command = f'"{sys.executable}" "{ROOT / "scripts" / "local_transcription_fixture_adapter.py"}" --input "{{input}}" --output "{{output}}"'
    monkeypatch.setenv(local_model_adapter.ENV_COMMAND, command)

    manifest = local_media_adapter.build_capability_manifest(project, fixture_path=wav, timeout=2.0)

    assert manifest["commercial_ready"] is False
    assert manifest["capabilities"]["transcription"]["commercial_ready"] is False
