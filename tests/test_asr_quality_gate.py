from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import asr_quality_gate
import local_media_adapter
import real_asr_adapter_contract

from test_real_asr_adapter_contract import write_real_asr_script


def make_wav(path: pathlib.Path) -> pathlib.Path:
    local_media_adapter.create_tiny_wav(path)
    return path


def test_quality_gate_contract_fixture_is_contract_only_not_production(tmp_path: pathlib.Path) -> None:
    samples = [make_wav(tmp_path / f"sample_{index}.wav") for index in range(3)]
    command = f'"{sys.executable}" "{ROOT / "scripts" / "real_asr_adapter_contract.py"}" --fixture-adapter --input "{{input}}" --output "{{output}}"'

    report = asr_quality_gate.run_quality_gate(
        project_dir=tmp_path,
        sample_paths=samples,
        env={real_asr_adapter_contract.ENV_COMMAND: command},
        timeout=2.0,
    )

    assert report["asr_quality_status"] == "contract_only"
    assert report["evidence_tier"] == "contract_fixture"
    assert report["sample_count"] == 3
    assert report["successful_samples"] == 3
    assert report["failed_samples"] == 0
    assert report["commercial_ready"] is False
    assert "contract_fixture_is_not_production_asr" in report["production_readiness_blockers"]
    assert (tmp_path / "asr_quality_report.json").exists()


def test_quality_gate_real_command_multi_sample_candidate_still_not_commercial(tmp_path: pathlib.Path) -> None:
    samples = [make_wav(tmp_path / f"sample_{index}.wav") for index in range(2)]
    script = write_real_asr_script(tmp_path / "asr_writer.py")
    env = {real_asr_adapter_contract.ENV_COMMAND: f'"{sys.executable}" "{script}" "{{input}}" "{{output}}" valid'}

    report = asr_quality_gate.run_quality_gate(project_dir=tmp_path, sample_paths=samples, env=env, timeout=2.0)

    assert report["asr_quality_status"] == "multi_sample_candidate"
    assert report["evidence_tier"] == "multi_sample_real"
    assert report["successful_samples"] == 2
    assert report["commercial_ready"] is False
    assert report["average_confidence"] == 0.98
    assert report["production_readiness_blockers"]


def test_quality_gate_invalid_json_and_timeout_are_bounded_failures(tmp_path: pathlib.Path) -> None:
    wav = make_wav(tmp_path / "sample.wav")
    script = write_real_asr_script(tmp_path / "asr_writer.py")
    invalid = asr_quality_gate.run_quality_gate(
        project_dir=tmp_path / "invalid",
        sample_paths=[wav],
        env={real_asr_adapter_contract.ENV_COMMAND: f'"{sys.executable}" "{script}" "{{input}}" "{{output}}" invalid_json'},
        timeout=2.0,
    )
    timed_out = asr_quality_gate.run_quality_gate(
        project_dir=tmp_path / "timeout",
        sample_paths=[wav],
        env={real_asr_adapter_contract.ENV_COMMAND: f'"{sys.executable}" "{script}" "{{input}}" "{{output}}" timeout'},
        timeout=0.2,
    )

    assert invalid["asr_quality_status"] == "failed"
    assert invalid["invalid_output_samples"] == 1
    assert timed_out["asr_quality_status"] == "not_ready"
    assert timed_out["timeout_samples"] == 1


def test_quality_gate_empty_text_or_segments_is_insufficient(tmp_path: pathlib.Path) -> None:
    wav = make_wav(tmp_path / "sample.wav")
    script = write_real_asr_script(tmp_path / "asr_writer.py")
    env = {real_asr_adapter_contract.ENV_COMMAND: f'"{sys.executable}" "{script}" "{{input}}" "{{output}}" empty_text'}

    report = asr_quality_gate.run_quality_gate(project_dir=tmp_path, sample_paths=[wav], env=env, timeout=2.0)

    assert report["asr_quality_status"] == "failed"
    assert "asr_sample_invalid_output" in report["production_readiness_blockers"]


def test_quality_gate_records_confidence_unavailable_reason(tmp_path: pathlib.Path) -> None:
    script = tmp_path / "no_confidence.py"
    script.write_text(
        "\n".join(
            [
                "import json, pathlib, sys",
                "input_path = pathlib.Path(sys.argv[1])",
                "output_path = pathlib.Path(sys.argv[2])",
                "doc = {'stage':'transcription','status':'verified','adapter_kind':'real_local_asr','engine':'unit','model_name':'unit','model_path':'local','input_path':str(input_path),'output_path':str(output_path),'created_at':'2026-01-01T00:00:00+00:00','language':'en','duration_seconds':0.1,'segments':[{'id':'s1','start':0,'end':0.1,'text':'hello'}],'text':'hello','confidence_unavailable_reason':'engine did not emit confidence','production_asr':True,'degraded':False,'evidence':['unit']}",
                "output_path.write_text(json.dumps(doc), encoding='utf-8')",
            ]
        ),
        encoding="utf-8",
    )
    wav = make_wav(tmp_path / "sample.wav")
    report = asr_quality_gate.run_quality_gate(
        project_dir=tmp_path,
        sample_paths=[wav],
        env={real_asr_adapter_contract.ENV_COMMAND: f'"{sys.executable}" "{script}" "{{input}}" "{{output}}"'},
        timeout=2.0,
    )

    assert report["average_confidence"] is None
    assert report["confidence_unavailable_reason"]
