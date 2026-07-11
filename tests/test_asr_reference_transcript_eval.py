from __future__ import annotations

import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import asr_reference_transcript_eval
import local_media_adapter


def build_reference_case(tmp_path: pathlib.Path, *, transcript_text: str = "hello local world", bad_hash: bool = False) -> tuple[pathlib.Path, list[dict]]:
    audio = tmp_path / "sample.wav"
    local_media_adapter.create_tiny_wav(audio, duration_seconds=0.2)
    transcript = tmp_path / "transcript.json"
    transcript.write_text(json.dumps({"text": transcript_text}), encoding="utf-8")
    manifest = tmp_path / "reference_transcripts.json"
    manifest.write_text(
        json.dumps(
            {
                "samples": [
                    {
                        "sample_id": "sample-1",
                        "audio_path": audio.name,
                        "reference_text": "Hello, local world!",
                        "language": "en",
                        "expected_min_duration": 0.1,
                        "sha256": "bad" if bad_hash else asr_reference_transcript_eval.sha256(audio),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return manifest, [{"input_path": str(audio), "transcript_path": str(transcript), "schema_valid": True}]


def test_reference_transcript_metrics_are_deterministic(tmp_path: pathlib.Path) -> None:
    manifest, samples = build_reference_case(tmp_path)

    first = asr_reference_transcript_eval.evaluate(project_dir=tmp_path, manifest_path=manifest, sample_results=samples)
    second = asr_reference_transcript_eval.evaluate(project_dir=tmp_path, manifest_path=manifest, sample_results=samples)

    assert first["status"] == "PASS"
    assert first["reference_transcript_coverage"] == 1.0
    assert first["quality_metrics"] == second["quality_metrics"]
    assert first["quality_metrics"] == {
        "normalized_text_match_rate": 1.0,
        "token_error_rate": 0.0,
        "character_error_rate": 0.0,
    }


def test_token_and_character_error_rates_are_reproducible(tmp_path: pathlib.Path) -> None:
    manifest, samples = build_reference_case(tmp_path, transcript_text="hello remote world")

    result = asr_reference_transcript_eval.evaluate(project_dir=tmp_path, manifest_path=manifest, sample_results=samples)

    assert result["quality_metrics"]["normalized_text_match_rate"] == 0.0
    assert result["quality_metrics"]["token_error_rate"] == 0.333333
    assert result["quality_metrics"]["character_error_rate"] > 0.0


def test_reference_audio_hash_mismatch_fails_verification(tmp_path: pathlib.Path) -> None:
    manifest, samples = build_reference_case(tmp_path, bad_hash=True)

    result = asr_reference_transcript_eval.evaluate(project_dir=tmp_path, manifest_path=manifest, sample_results=samples)

    assert result["status"] == "NOT_READY"
    assert result["reference_transcript_coverage"] == 0.0
    assert any("reference_audio_sha256_mismatch" in item for item in result["blockers"])


def test_missing_reference_manifest_has_zero_coverage(tmp_path: pathlib.Path) -> None:
    result = asr_reference_transcript_eval.evaluate(project_dir=tmp_path, manifest_path=None, sample_results=[])

    assert result["reference_transcript_coverage"] == 0.0
    assert "missing_reference_transcripts" in result["blockers"]
