from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import local_media_adapter


def test_python_standard_library_generates_and_reads_tiny_wav(tmp_path: pathlib.Path) -> None:
    wav = tmp_path / "fixtures" / "sample_audio.wav"

    record = local_media_adapter.create_tiny_wav(wav)
    metadata = local_media_adapter.read_wave_metadata(wav)

    assert wav.exists()
    assert record["sha256"] == local_media_adapter.sha256(wav)
    assert record["size"] == wav.stat().st_size
    assert metadata["duration_seconds"] > 0
    assert metadata["framerate"] == 8000
    assert metadata["channels"] == 1


def test_capability_manifest_records_wave_metadata_and_unavailable_tools(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: None)
    wav = tmp_path / "project" / "fixtures" / "sample_audio.wav"
    local_media_adapter.create_tiny_wav(wav)

    manifest = local_media_adapter.build_capability_manifest(tmp_path / "project", fixture_path=wav, timeout=0.1)

    assert manifest["selected_adapter"] == "python_wave_verified"
    assert manifest["commercial_ready"] is False
    assert manifest["capabilities"]["media_fixture"]["type"] == "wav"
    assert manifest["capabilities"]["media_fixture"]["sha256"] == local_media_adapter.sha256(wav)
    assert manifest["capabilities"]["media_fixture"]["size"] == wav.stat().st_size
    assert manifest["capabilities"]["media_metadata"]["status"] == "python_wave_verified"
    assert manifest["tool_detection"]["ffprobe"]["status"] == "local_tool_unavailable"
    assert manifest["tool_detection"]["ffmpeg"]["status"] == "local_tool_unavailable"
    assert manifest["capabilities"]["audio_extract"]["status"] == "unavailable"
    assert manifest["capabilities"]["transcription"]["status"] == "placeholder_transcription"
    assert manifest["capabilities"]["transcription"]["model"] is None
    assert manifest["capabilities"]["transcription"]["commercial_ready"] is False
    assert manifest["capabilities"]["transcription"]["artifact"]["sha256"]


def test_ffprobe_and_ffmpeg_verified_branch_records_bounded_commands(tmp_path: pathlib.Path, monkeypatch) -> None:
    wav = tmp_path / "project" / "fixtures" / "sample_audio.wav"
    local_media_adapter.create_tiny_wav(wav)

    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: f"/fake/{name}")

    def fake_run(command: list[str], *, timeout: float = 2.0) -> dict:
        if "ffprobe" in command[0] and "-show_entries" in command:
            return {"command": command, "returncode": 0, "duration_seconds": 0.01, "stdout": "{\"streams\":[]}", "stderr": "", "timed_out": False}
        return {"command": command, "returncode": 0, "duration_seconds": 0.01, "stdout": f"{pathlib.Path(command[0]).name} version test", "stderr": "", "timed_out": False}

    monkeypatch.setattr(local_media_adapter, "run_bounded", fake_run)

    manifest = local_media_adapter.build_capability_manifest(tmp_path / "project", fixture_path=wav, timeout=0.1)

    assert manifest["selected_adapter"] == "local_tool_verified"
    assert manifest["capabilities"]["media_metadata"]["status"] == "ffprobe_verified"
    assert manifest["capabilities"]["media_metadata"]["tool"] == "ffprobe"
    assert manifest["tool_detection"]["ffprobe"]["command"]
    assert manifest["tool_detection"]["ffprobe"]["returncode"] == 0
    assert manifest["capabilities"]["audio_extract"]["status"] == "verified"
    assert manifest["capabilities"]["audio_extract"]["tool"] == "ffmpeg"
    assert manifest["commercial_ready"] is False
    assert manifest["capabilities"]["transcription"]["status"] == "placeholder_transcription"


def test_cli_writes_capability_manifest(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: None)
    project = tmp_path / "project"
    output = project / "capability_manifest.json"

    manifest = local_media_adapter.build_capability_manifest(project, output_path=output, timeout=0.1)
    loaded = json.loads(output.read_text(encoding="utf-8"))

    assert loaded["selected_adapter"] == manifest["selected_adapter"]
    assert loaded["capabilities"]["media_metadata"]["evidence"]
