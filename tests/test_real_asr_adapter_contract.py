from __future__ import annotations

import json
import pathlib
import sys

import pytest

pytestmark = pytest.mark.slow

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import capability_manifest_check
import delivery_evidence_builder
import implementation_structure_materializer
import local_media_adapter
import local_model_adapter
import real_asr_adapter_contract

SUBPROCESS_TEST_TIMEOUT = 5.0


def read_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_real_asr_script(path: pathlib.Path, *, mode: str = "valid") -> pathlib.Path:
    path.write_text(
        "\n".join(
            [
                "import json, pathlib, sys, time",
                "input_path = pathlib.Path(sys.argv[1])",
                "output_path = pathlib.Path(sys.argv[2])",
                "mode = sys.argv[3] if len(sys.argv) > 3 else 'valid'",
                "if mode == 'timeout':",
                "    time.sleep(5)",
                "if mode == 'returncode':",
                "    sys.exit(7)",
                "output_path.parent.mkdir(parents=True, exist_ok=True)",
                "if mode == 'invalid_json':",
                "    output_path.write_text('{not json', encoding='utf-8')",
                "    sys.exit(0)",
                "doc = {",
                "  'stage': 'transcription',",
                "  'status': 'verified',",
                "  'adapter_kind': 'real_local_asr',",
                "  'engine': 'unit_test_real_asr_engine',",
                "  'model_name': 'unit-test-model',",
                "  'model_path': 'local-test-model-path',",
                "  'input_path': str(input_path),",
                "  'output_path': str(output_path),",
                "  'created_at': '2026-01-01T00:00:00+00:00',",
                "  'language': 'en',",
                "  'duration_seconds': 0.25,",
                "  'segments': [{'id': 's1', 'start': 0, 'end': 0.25, 'text': 'hello from real asr contract', 'confidence': 0.98}],",
                "  'text': 'hello from real asr contract',",
                "  'confidence': 0.98,",
                "  'production_asr': True,",
                "  'degraded': False,",
                "  'evidence': ['unit test real ASR contract command'],",
                "}",
                "if mode == 'production_false': doc['production_asr'] = False",
                "if mode == 'degraded_true': doc['degraded'] = True",
                "if mode == 'missing_field':",
                "    del doc['engine']",
                "    del doc['model_name']",
                "if mode == 'empty_text': doc['text'] = ''",
                "if mode == 'empty_segments': doc['segments'] = []",
                "output_path.write_text(json.dumps(doc), encoding='utf-8')",
            ]
        ),
        encoding="utf-8",
    )
    return path


def make_wav(path: pathlib.Path) -> pathlib.Path:
    local_media_adapter.create_tiny_wav(path)
    return path


def test_no_real_asr_configuration_records_no_asr_configured(tmp_path: pathlib.Path) -> None:
    wav = make_wav(tmp_path / "input.wav")

    result = real_asr_adapter_contract.evaluate(project_dir=tmp_path, input_path=wav, env={}, timeout=0.1)

    assert result["status"] == "no_asr_configured"
    assert result["adapter_kind"] == "none"
    assert result["commercial_ready"] is False


def test_placeholder_and_fixture_transcription_do_not_become_real_asr(tmp_path: pathlib.Path) -> None:
    wav = make_wav(tmp_path / "input.wav")
    placeholder = {"status": "placeholder_transcription", "tool": "none", "commercial_ready": False}
    fixture = {"status": "local_model_verified", "adapter": "local_transcription_fixture_adapter", "not_production_asr": True}

    placeholder_result = real_asr_adapter_contract.evaluate(project_dir=tmp_path, input_path=wav, env={}, fallback_transcription=placeholder)
    fixture_result = real_asr_adapter_contract.evaluate(project_dir=tmp_path, input_path=wav, env={}, fallback_transcription=fixture)

    assert placeholder_result["status"] == "placeholder_transcription"
    assert fixture_result["status"] == "command_fixture_transcription"
    assert fixture_result["adapter_kind"] == "fixture"
    assert placeholder_result["production_asr"] is False
    assert fixture_result["production_asr"] is False


def test_real_asr_command_success_records_verified_hash_size_and_schema(tmp_path: pathlib.Path) -> None:
    wav = make_wav(tmp_path / "input.wav")
    output = tmp_path / "real_asr_transcript.json"
    script = write_real_asr_script(tmp_path / "asr_writer.py")
    env = {real_asr_adapter_contract.ENV_COMMAND: f'"{sys.executable}" "{script}" "{{input}}" "{{output}}" valid'}

    result = real_asr_adapter_contract.evaluate(
        project_dir=tmp_path,
        input_path=wav,
        output_path=output,
        env=env,
        timeout=SUBPROCESS_TEST_TIMEOUT,
    )

    assert result["status"] == "real_local_asr_verified"
    assert result["evidence_tier"] == "single_sample_real"
    assert result["adapter_kind"] == "real_local_asr"
    assert result["schema_valid"] is True
    assert result["returncode"] == 0
    assert result["timed_out"] is False
    assert result["sha256"] == real_asr_adapter_contract.sha256(output)
    assert result["size"] == output.stat().st_size
    assert result["input_sha256"] == real_asr_adapter_contract.sha256(wav)
    assert result["production_asr"] is False
    assert result["commercial_ready"] is False


def test_real_asr_rejects_non_production_or_degraded_output(tmp_path: pathlib.Path) -> None:
    wav = make_wav(tmp_path / "input.wav")
    script = write_real_asr_script(tmp_path / "asr_writer.py")
    for mode, expected in [("production_false", "production_asr_not_true"), ("degraded_true", "degraded_not_false")]:
        output = tmp_path / f"{mode}.json"
        env = {real_asr_adapter_contract.ENV_COMMAND: f'"{sys.executable}" "{script}" "{{input}}" "{{output}}" {mode}'}
        result = real_asr_adapter_contract.evaluate(
            project_dir=tmp_path,
            input_path=wav,
            output_path=output,
            env=env,
            timeout=SUBPROCESS_TEST_TIMEOUT,
        )
        assert result["status"] == "real_asr_invalid_output"
        assert expected in result["schema_blockers"]


def test_real_asr_invalid_json_schema_empty_text_and_segments_are_invalid(tmp_path: pathlib.Path) -> None:
    wav = make_wav(tmp_path / "input.wav")
    script = write_real_asr_script(tmp_path / "asr_writer.py")
    cases = {
        "invalid_json": "invalid_json:",
        "missing_field": "engine_or_model_name_missing",
        "empty_text": "text_empty",
        "empty_segments": "segments_empty",
    }
    for mode, expected in cases.items():
        output = tmp_path / f"{mode}.json"
        env = {real_asr_adapter_contract.ENV_COMMAND: f'"{sys.executable}" "{script}" "{{input}}" "{{output}}" {mode}'}
        result = real_asr_adapter_contract.evaluate(
            project_dir=tmp_path,
            input_path=wav,
            output_path=output,
            env=env,
            timeout=SUBPROCESS_TEST_TIMEOUT,
        )
        assert result["status"] == "real_asr_invalid_output"
        assert any(str(item).startswith(expected) or item == expected for item in result["schema_blockers"])


def test_real_asr_returncode_and_timeout_are_bounded_failures(tmp_path: pathlib.Path) -> None:
    wav = make_wav(tmp_path / "input.wav")
    script = write_real_asr_script(tmp_path / "asr_writer.py")

    failed = real_asr_adapter_contract.evaluate(
        project_dir=tmp_path,
        input_path=wav,
        env={real_asr_adapter_contract.ENV_COMMAND: f'"{sys.executable}" "{script}" "{{input}}" "{{output}}" returncode'},
        timeout=SUBPROCESS_TEST_TIMEOUT,
    )
    timed_out = real_asr_adapter_contract.evaluate(
        project_dir=tmp_path,
        input_path=wav,
        env={real_asr_adapter_contract.ENV_COMMAND: f'"{sys.executable}" "{script}" "{{input}}" "{{output}}" timeout'},
        timeout=0.2,
    )

    assert failed["status"] == "real_asr_failed"
    assert failed["returncode"] == 7
    assert timed_out["status"] == "real_asr_timeout"
    assert timed_out["timed_out"] is True


def test_capability_manifest_asr_section_rejects_fixture_as_real(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: None)
    project = tmp_path / "project"
    wav = make_wav(project / "fixtures" / "sample_audio.wav")
    manifest = local_media_adapter.build_capability_manifest(project, fixture_path=wav, timeout=0.1)

    assert manifest["capabilities"]["asr"]["status"] == "placeholder_transcription"
    assert manifest["capabilities"]["asr"]["commercial_ready"] is False
    result = capability_manifest_check.check(project / "capability_manifest.json", project_dir=project)
    assert result["status"] == "PASS"

    tampered = read_json(project / "capability_manifest.json")
    tampered["capabilities"]["asr"]["status"] = "asr_contract_fixture_verified"
    tampered["capabilities"]["asr"]["adapter_kind"] = "fixture"
    tampered["capabilities"]["asr"]["evidence_tier"] = "contract_fixture"
    tampered["capabilities"]["asr"]["production_asr"] = True
    (project / "capability_manifest.json").write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = capability_manifest_check.check(project / "capability_manifest.json", project_dir=project)
    assert result["status"] == "FAIL"
    assert "asr_contract_fixture_claims_production" in result["blockers"]


def test_delivery_manifest_and_reports_reference_real_asr_contract_fixture(tmp_path: pathlib.Path, monkeypatch) -> None:
    monkeypatch.setattr(local_media_adapter.shutil, "which", lambda name: None)
    project = tmp_path / "generated_project"
    run_dir = tmp_path / "run"
    implementation_structure_materializer.materialize(project_dir=project, run_dir=run_dir)
    asr_command = f'"{sys.executable}" "{project / "real_asr_adapter_contract.py"}" --fixture-adapter --input "{{input}}" --output "{{output}}"'
    monkeypatch.setenv(real_asr_adapter_contract.ENV_COMMAND, asr_command)

    result = delivery_evidence_builder.build(
        project_dir=project,
        run_dir=run_dir,
        smoke_command=[sys.executable, "cli.py", "--input", "fixtures/sample_audio.wav", "--output-dir", "."],
        capture_screenshot=True,
    )

    assert result["status"] == "NEEDS_REWORK"
    delivery_manifest = read_json(project / "delivery_evidence_manifest.json")
    asr = delivery_manifest["capability_manifest"]["capabilities"]["asr"]
    assert asr["status"] == "asr_contract_fixture_verified"
    assert asr["evidence_tier"] == "contract_fixture"
    assert asr["production_asr"] is False
    assert asr["commercial_ready"] is False
    assert "real_asr_transcript.json" in delivery_manifest["files"]
    assert "asr_quality_report.json" in delivery_manifest["files"]
    assert "asr_status: asr_contract_fixture_verified" in (project / "TEST_REPORT.md").read_text(encoding="utf-8")
    assert "asr_evidence_tier: contract_fixture" in (project / "TEST_REPORT.md").read_text(encoding="utf-8")
    assert "ASR contract fixtures validate" in (project / "DELIVERY_NOTES.md").read_text(encoding="utf-8")
