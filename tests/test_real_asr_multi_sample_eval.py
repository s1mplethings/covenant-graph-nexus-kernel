from __future__ import annotations

import json
import pathlib
import sys

import pytest

pytestmark = pytest.mark.slow

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import local_media_adapter
import real_asr_adapter_contract
import real_asr_multi_sample_eval
import delivery_evidence_builder
import implementation_structure_materializer


def make_samples(root: pathlib.Path, count: int = 3) -> list[pathlib.Path]:
    samples: list[pathlib.Path] = []
    for index in range(count):
        path = root / f"sample_{index + 1}.wav"
        local_media_adapter.create_tiny_wav(path, duration_seconds=0.1 + (index * 0.02))
        samples.append(path)
    return samples


def write_adapter(path: pathlib.Path) -> pathlib.Path:
    path.write_text(
        "\n".join(
            [
                "import json, pathlib, sys, time",
                "source = pathlib.Path(sys.argv[1])",
                "output = pathlib.Path(sys.argv[2])",
                "mode = sys.argv[3] if len(sys.argv) > 3 else 'valid'",
                "if mode == 'by_name': mode = source.stem.split('_')[-1]",
                "if mode == 'timeout': time.sleep(5)",
                "if mode == 'returncode': sys.exit(9)",
                "output.parent.mkdir(parents=True, exist_ok=True)",
                "if mode == 'invalid': output.write_text('{bad json', encoding='utf-8'); sys.exit(0)",
                "text = '' if mode == 'emptytext' else 'bounded local transcript'",
                "segments = [] if mode == 'emptysegments' else [{'id':'s1','start':0,'end':0.1,'text':text,'confidence':0.97}]",
                "doc = {'stage':'transcription','status':'verified','adapter_kind':'real_local_asr','engine':'test-local-engine','model_name':'test-local-model','model_path':'local-test-path','input_path':str(source),'output_path':str(output),'created_at':'2026-01-01T00:00:00+00:00','language':'en','duration_seconds':0.1,'segments':segments,'text':text,'confidence':0.97,'production_asr':True,'degraded':False,'evidence':['bounded evaluation fixture; not production proof']}",
                "if mode == 'noconfidence': doc.pop('confidence'); [item.pop('confidence', None) for item in doc['segments']]; doc['confidence_unavailable_reason']='engine did not emit confidence'",
                "output.write_text(json.dumps(doc), encoding='utf-8')",
            ]
        ),
        encoding="utf-8",
    )
    return path


def real_env(script: pathlib.Path, mode: str = "valid") -> dict[str, str]:
    return {
        real_asr_adapter_contract.ENV_COMMAND: f'"{sys.executable}" "{script}" "{{input}}" "{{output}}" {mode}',
        real_asr_multi_sample_eval.ENV_ADAPTER_KIND: "real_local_asr",
    }


def test_no_command_is_not_ready_and_has_no_production_claim(tmp_path: pathlib.Path) -> None:
    report = real_asr_multi_sample_eval.evaluate(project_dir=tmp_path, sample_paths=make_samples(tmp_path), env={})

    assert report["asr_quality_status"] == "not_ready"
    assert report["evidence_tier"] == "none"
    assert report["production_candidate"] is False
    assert report["commercial_ready"] is False


def test_fixture_multi_sample_stays_contract_only(tmp_path: pathlib.Path) -> None:
    samples = make_samples(tmp_path)
    command = f'"{sys.executable}" "{ROOT / "scripts" / "real_asr_adapter_contract.py"}" --fixture-adapter --input "{{input}}" --output "{{output}}"'
    report = real_asr_multi_sample_eval.evaluate(
        project_dir=tmp_path,
        sample_paths=samples,
        env={real_asr_adapter_contract.ENV_COMMAND: command},
        adapter_kind="fixture",
    )

    assert report["adapter_kind"] == "fixture"
    assert report["asr_quality_status"] == "contract_only"
    assert report["evidence_tier"] == "contract_fixture"
    assert report["successful_samples"] == 3
    assert report["production_candidate"] is False
    assert report["production_verified"] is False
    assert report["commercial_ready"] is False


def test_real_three_sample_threshold_pass_is_candidate_not_verified(tmp_path: pathlib.Path) -> None:
    script = write_adapter(tmp_path / "adapter.py")
    report = real_asr_multi_sample_eval.evaluate(
        project_dir=tmp_path,
        sample_paths=make_samples(tmp_path),
        env=real_env(script),
        adapter_kind="real_local_asr",
    )

    assert report["asr_quality_status"] == "production_candidate"
    assert report["evidence_tier"] == "production_candidate"
    assert report["sample_count"] == report["successful_samples"] == 3
    assert report["success_rate"] == 1.0
    assert report["non_empty_text_rate"] == 1.0
    assert report["non_empty_segments_rate"] == 1.0
    assert report["production_candidate"] is True
    assert report["production_verified"] is False
    assert report["commercial_ready"] is False
    assert "production_candidate_is_not_production_verified" in report["production_readiness_blockers"]
    required = {
        "input_path", "input_sha256", "input_size", "command", "returncode", "timed_out",
        "transcript_path", "transcript_sha256", "transcript_size", "schema_valid", "text_non_empty",
        "segments_non_empty", "confidence", "confidence_unavailable_reason", "duration_seconds", "status", "failure_reason",
    }
    assert required <= set(report["sample_results"][0])


def test_single_sample_cannot_be_production_candidate(tmp_path: pathlib.Path) -> None:
    script = write_adapter(tmp_path / "adapter.py")
    report = real_asr_multi_sample_eval.evaluate(
        project_dir=tmp_path,
        sample_paths=make_samples(tmp_path, 1),
        env=real_env(script),
        adapter_kind="real_local_asr",
    )

    assert report["asr_quality_status"] == "single_sample_only"
    assert report["production_candidate"] is False
    assert "sample_count_below_minimum" in report["production_readiness_blockers"]


@pytest.mark.parametrize(
    ("mode", "expected_counter", "expected_blocker"),
    [
        ("invalid", "invalid_output_samples", "invalid_output_count_above_threshold"),
        ("returncode", "failed_samples", "success_rate_below_threshold"),
    ],
)
def test_invalid_and_nonzero_samples_are_counted(
    tmp_path: pathlib.Path, mode: str, expected_counter: str, expected_blocker: str
) -> None:
    script = write_adapter(tmp_path / "adapter.py")
    report = real_asr_multi_sample_eval.evaluate(
        project_dir=tmp_path,
        sample_paths=make_samples(tmp_path),
        env=real_env(script, mode),
        adapter_kind="real_local_asr",
    )

    assert report["asr_quality_status"] == "asr_quality_insufficient"
    assert report[expected_counter] == 3
    assert expected_blocker in report["production_readiness_blockers"]


def test_timeout_is_bounded_and_counted(tmp_path: pathlib.Path) -> None:
    script = write_adapter(tmp_path / "adapter.py")
    report = real_asr_multi_sample_eval.evaluate(
        project_dir=tmp_path,
        sample_paths=make_samples(tmp_path),
        env=real_env(script, "timeout"),
        adapter_kind="real_local_asr",
        timeout=0.1,
    )

    assert report["timeout_samples"] == 3
    assert report["failed_samples"] == 3
    assert "timeout_count_above_threshold" in report["production_readiness_blockers"]


@pytest.mark.parametrize(
    ("mode", "rate_field", "blocker"),
    [
        ("emptytext", "non_empty_text_rate", "non_empty_text_rate_below_threshold"),
        ("emptysegments", "non_empty_segments_rate", "non_empty_segments_rate_below_threshold"),
    ],
)
def test_empty_content_rates_fail_quality_threshold(
    tmp_path: pathlib.Path, mode: str, rate_field: str, blocker: str
) -> None:
    script = write_adapter(tmp_path / "adapter.py")
    report = real_asr_multi_sample_eval.evaluate(
        project_dir=tmp_path,
        sample_paths=make_samples(tmp_path),
        env=real_env(script, mode),
        adapter_kind="real_local_asr",
    )

    assert report["asr_quality_status"] == "asr_quality_insufficient"
    assert report[rate_field] == 0.0
    assert blocker in report["production_readiness_blockers"]


def test_missing_confidence_with_reason_is_recorded(tmp_path: pathlib.Path) -> None:
    script = write_adapter(tmp_path / "adapter.py")
    report = real_asr_multi_sample_eval.evaluate(
        project_dir=tmp_path,
        sample_paths=make_samples(tmp_path),
        env=real_env(script, "noconfidence"),
        adapter_kind="real_local_asr",
    )

    assert report["average_confidence"] is None
    assert all(item["confidence_unavailable_reason"] for item in report["sample_results"])
    assert report["production_candidate"] is True


def test_report_is_written_with_thresholds_and_hashes(tmp_path: pathlib.Path) -> None:
    script = write_adapter(tmp_path / "adapter.py")
    output = tmp_path / "evidence" / "multi.json"
    report = real_asr_multi_sample_eval.evaluate(
        project_dir=tmp_path,
        sample_paths=make_samples(tmp_path),
        output_path=output,
        env=real_env(script),
        adapter_kind="real_local_asr",
    )

    on_disk = json.loads(output.read_text(encoding="utf-8"))
    assert on_disk == report
    assert report["thresholds"]["min_samples"] == 3
    assert all(item["input_sha256"] and item["transcript_sha256"] for item in report["sample_results"])


def test_delivery_evidence_references_multi_sample_fixture_report(tmp_path: pathlib.Path, monkeypatch) -> None:
    project = tmp_path / "project"
    run_dir = tmp_path / "run"
    implementation_structure_materializer.materialize(project_dir=project, run_dir=run_dir)
    command = f'"{sys.executable}" "{project / "real_asr_adapter_contract.py"}" --fixture-adapter --input "{{input}}" --output "{{output}}"'
    monkeypatch.setenv(real_asr_adapter_contract.ENV_COMMAND, command)
    monkeypatch.setenv(real_asr_multi_sample_eval.ENV_ADAPTER_KIND, "fixture")
    monkeypatch.setenv("CGKN_REAL_ASR_MULTI_SAMPLE_EVAL", "1")
    monkeypatch.setenv("CGKN_ASR_QUALITY_GATE_SAMPLE_COUNT", "3")

    result = delivery_evidence_builder.build(
        project_dir=project,
        run_dir=run_dir,
        smoke_command=[sys.executable, "cli.py", "--input", "fixtures/sample_audio.wav", "--output-dir", "."],
        capture_screenshot=True,
    )

    assert result["status"] == "PASS"
    manifest = json.loads((project / "delivery_manifest.json").read_text(encoding="utf-8"))
    assert "asr_multi_sample_report.json" in manifest["files"]
    assert manifest["capability_manifest"]["capabilities"]["asr_quality"]["asr_quality_status"] == "contract_only"
    test_report = (project / "TEST_REPORT.md").read_text(encoding="utf-8")
    notes = (project / "DELIVERY_NOTES.md").read_text(encoding="utf-8")
    assert "asr_quality_status: contract_only" in test_report
    assert "asr_production_candidate: False" in test_report
    assert "production blockers" in notes
    assert "not production verified" in notes
