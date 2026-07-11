from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import local_media_adapter
import local_model_adapter


def wav_fixture(tmp_path: pathlib.Path) -> pathlib.Path:
    wav = tmp_path / "project" / "fixtures" / "sample_audio.wav"
    local_media_adapter.create_tiny_wav(wav)
    return wav


def test_no_configuration_records_local_model_unavailable(tmp_path: pathlib.Path) -> None:
    wav = wav_fixture(tmp_path)

    result = local_model_adapter.evaluate(project_dir=tmp_path / "project", input_path=wav, env={}, timeout=0.1)

    assert result["status"] == "local_model_unavailable"
    assert result["commercial_ready"] is False
    assert result["command"] is None
    assert result["output_artifact"] == ""


def test_placeholder_mode_writes_degraded_transcript_artifact(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    wav = wav_fixture(tmp_path)
    output = project / "placeholder_transcript.json"

    result = local_model_adapter.evaluate(project_dir=project, input_path=wav, output_path=output, env={}, timeout=0.1, placeholder=True)
    transcript = json.loads(output.read_text(encoding="utf-8"))

    assert result["status"] == "placeholder_transcription"
    assert result["commercial_ready"] is False
    assert result["model_status"] == "local_model_unavailable"
    assert result["artifact"]["sha256"] == local_media_adapter.sha256(output)
    assert result["artifact"]["size"] == output.stat().st_size
    assert transcript["stage"] == "transcription"
    assert transcript["status"] == "placeholder"
    assert transcript["degraded"] is True
    assert "not model output" in transcript["text"]


def test_configured_command_success_records_verified_artifact(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    wav = wav_fixture(tmp_path)
    writer = tmp_path / "write_transcript.py"
    writer.write_text(
        "\n".join(
            [
                "import json, pathlib, sys",
                "input_path = pathlib.Path(sys.argv[1])",
                "output_path = pathlib.Path(sys.argv[2])",
                "output_path.write_text(json.dumps({",
                "  'stage': 'transcription',",
                "  'status': 'verified',",
                "  'adapter': 'unit_local_adapter',",
                "  'input_path': str(input_path),",
                "  'output_path': str(output_path),",
                "  'created_at': 'test',",
                "  'segments': [{'id': 'seg1', 'text': 'verified local command'}],",
                "  'text': 'verified local command',",
                "  'degraded': False,",
                "  'not_production_asr': True,",
                "  'evidence': ['unit smoke']",
                "}, ensure_ascii=False), encoding='utf-8')",
            ]
        ),
        encoding="utf-8",
    )
    output = project / "verified_transcript.json"
    env = {local_model_adapter.ENV_COMMAND: f'"{sys.executable}" "{writer}" "{{input}}" "{{output}}"'}

    result = local_model_adapter.evaluate(project_dir=project, input_path=wav, output_path=output, env=env, timeout=2.0)

    assert result["status"] == "local_model_verified"
    assert result["returncode"] == 0
    assert result["adapter"] == "unit_local_adapter"
    assert result["artifact"]["sha256"] == local_media_adapter.sha256(output)
    assert result["artifact"]["size"] == output.stat().st_size
    assert result["not_production_asr"] is True
    assert result["commercial_ready"] is False


def test_configured_command_invalid_schema_fails_without_fake_pass(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    wav = wav_fixture(tmp_path)
    writer = tmp_path / "write_bad.py"
    writer.write_text("import pathlib, sys; pathlib.Path(sys.argv[2]).write_text('{\"status\":\"ok\"}', encoding='utf-8')", encoding="utf-8")
    output = project / "bad_transcript.json"
    env = {local_model_adapter.ENV_COMMAND: f'"{sys.executable}" "{writer}" "{{input}}" "{{output}}"'}

    result = local_model_adapter.evaluate(project_dir=project, input_path=wav, output_path=output, env=env, timeout=2.0)

    assert result["status"] == "failed"
    assert result["commercial_ready"] is False
    assert any("schema_blockers" in item for item in result["evidence"] if isinstance(item, dict))


def test_configured_command_timeout_is_failed_and_bounded(tmp_path: pathlib.Path) -> None:
    project = tmp_path / "project"
    wav = wav_fixture(tmp_path)
    sleeper = tmp_path / "sleep.py"
    sleeper.write_text("import time; time.sleep(5)", encoding="utf-8")
    env = {local_model_adapter.ENV_COMMAND: f'"{sys.executable}" "{sleeper}" "{{input}}" "{{output}}"'}

    result = local_model_adapter.evaluate(project_dir=project, input_path=wav, env=env, timeout=0.2)

    assert result["status"] == "failed"
    assert result["returncode"] is None
    assert result["evidence"][0]["timed_out"] is True
    assert result["commercial_ready"] is False
