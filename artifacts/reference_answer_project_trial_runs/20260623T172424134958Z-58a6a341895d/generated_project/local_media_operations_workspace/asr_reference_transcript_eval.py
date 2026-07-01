from __future__ import annotations

import hashlib
import json
import pathlib
import re
import wave
from datetime import datetime, timezone
from typing import Any, Sequence


REQUIRED_REFERENCE_FIELDS = {
    "sample_id",
    "audio_path",
    "reference_text",
    "language",
    "expected_min_duration",
    "sha256",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value: str) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def edit_distance(reference: Sequence[Any], hypothesis: Sequence[Any]) -> int:
    previous = list(range(len(hypothesis) + 1))
    for ref_index, ref_item in enumerate(reference, start=1):
        current = [ref_index]
        for hyp_index, hyp_item in enumerate(hypothesis, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[hyp_index] + 1,
                    previous[hyp_index - 1] + (0 if ref_item == hyp_item else 1),
                )
            )
        previous = current
    return previous[-1]


def text_metrics(reference_text: str, transcript_text: str) -> dict[str, Any]:
    reference = normalize_text(reference_text)
    transcript = normalize_text(transcript_text)
    reference_tokens = reference.split()
    transcript_tokens = transcript.split()
    token_errors = edit_distance(reference_tokens, transcript_tokens)
    character_errors = edit_distance(list(reference), list(transcript))
    return {
        "normalized_text_match": reference == transcript,
        "token_errors": token_errors,
        "reference_token_count": len(reference_tokens),
        "token_error_rate": round(token_errors / max(1, len(reference_tokens)), 6),
        "character_errors": character_errors,
        "reference_character_count": len(reference),
        "character_error_rate": round(character_errors / max(1, len(reference)), 6),
    }


def _duration(path: pathlib.Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() / max(1, handle.getframerate())
    except Exception:
        return 0.0


def _read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def _resolve(project: pathlib.Path, raw_path: str) -> pathlib.Path:
    path = pathlib.Path(str(raw_path or ""))
    return path if path.is_absolute() else project / path


def evaluate(
    *,
    project_dir: pathlib.Path,
    manifest_path: pathlib.Path | None,
    sample_results: list[dict[str, Any]],
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    sample_count = len(sample_results)
    if not manifest_path:
        return {
            "generated_at": now(),
            "status": "NOT_READY",
            "manifest_path": "",
            "sample_count": sample_count,
            "reference_count": 0,
            "verified_reference_count": 0,
            "reference_transcript_coverage": 0.0,
            "quality_metrics": {
                "normalized_text_match_rate": 0.0,
                "token_error_rate": None,
                "character_error_rate": None,
            },
            "sample_evaluations": [],
            "blockers": ["missing_reference_transcripts"],
        }
    manifest = pathlib.Path(manifest_path)
    if not manifest.is_absolute():
        manifest = project / manifest
    if not manifest.exists() or not manifest.is_file():
        result = evaluate(project_dir=project, manifest_path=None, sample_results=sample_results)
        result["manifest_path"] = str(manifest)
        return result
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "generated_at": now(),
            "status": "FAIL",
            "manifest_path": str(manifest),
            "sample_count": sample_count,
            "reference_count": 0,
            "verified_reference_count": 0,
            "reference_transcript_coverage": 0.0,
            "quality_metrics": {"normalized_text_match_rate": 0.0, "token_error_rate": None, "character_error_rate": None},
            "sample_evaluations": [],
            "blockers": [f"reference_manifest_invalid_json:{exc}"],
        }
    entries = raw.get("samples", []) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        entries = []
    blockers: list[str] = []
    evaluations: list[dict[str, Any]] = []
    sample_by_path: dict[str, dict[str, Any]] = {}
    for sample in sample_results:
        input_path = _resolve(project, str(sample.get("input_path") or "")).resolve()
        sample_by_path[str(input_path).lower()] = sample
        sample_by_path[input_path.name.lower()] = sample
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            blockers.append(f"reference_entry_{index}_not_object")
            continue
        missing = sorted(REQUIRED_REFERENCE_FIELDS - set(entry))
        sample_id = str(entry.get("sample_id") or f"sample_{index}")
        if missing:
            blockers.extend(f"{sample_id}:{field}_missing" for field in missing)
            continue
        audio = _resolve(project, str(entry["audio_path"])).resolve()
        item_blockers: list[str] = []
        if not audio.exists() or not audio.is_file():
            item_blockers.append("reference_audio_missing")
        elif sha256(audio) != str(entry["sha256"]):
            item_blockers.append("reference_audio_sha256_mismatch")
        if audio.exists() and _duration(audio) < float(entry.get("expected_min_duration") or 0.0):
            item_blockers.append("reference_audio_duration_below_minimum")
        sample = sample_by_path.get(str(audio).lower()) or sample_by_path.get(audio.name.lower())
        if sample is None:
            item_blockers.append("asr_sample_result_missing")
        transcript_path = _resolve(project, str((sample or {}).get("transcript_path") or ""))
        transcript = _read_json(transcript_path) if transcript_path.exists() else {}
        if not transcript:
            item_blockers.append("transcript_artifact_missing_or_invalid")
        metrics = text_metrics(str(entry.get("reference_text") or ""), str(transcript.get("text") or "")) if transcript else {}
        evaluations.append(
            {
                "sample_id": sample_id,
                "audio_path": str(audio),
                "audio_sha256": sha256(audio) if audio.exists() and audio.is_file() else "",
                "language": str(entry.get("language") or ""),
                "transcript_path": str(transcript_path),
                "schema_valid": bool((sample or {}).get("schema_valid")),
                "metrics": metrics,
                "status": "PASS" if not item_blockers else "FAIL",
                "blockers": item_blockers,
            }
        )
        blockers.extend(f"{sample_id}:{item}" for item in item_blockers)
    verified = [item for item in evaluations if item["status"] == "PASS"]
    total_ref_tokens = sum(int(item["metrics"].get("reference_token_count", 0)) for item in verified)
    total_token_errors = sum(int(item["metrics"].get("token_errors", 0)) for item in verified)
    total_ref_chars = sum(int(item["metrics"].get("reference_character_count", 0)) for item in verified)
    total_char_errors = sum(int(item["metrics"].get("character_errors", 0)) for item in verified)
    coverage = round(len(verified) / max(1, sample_count), 6) if sample_count else 0.0
    if coverage == 0.0 and "missing_reference_transcripts" not in blockers:
        blockers.append("missing_reference_transcripts")
    metrics = {
        "normalized_text_match_rate": round(
            sum(1 for item in verified if item["metrics"].get("normalized_text_match")) / max(1, len(verified)), 6
        ) if verified else 0.0,
        "token_error_rate": round(total_token_errors / max(1, total_ref_tokens), 6) if verified else None,
        "character_error_rate": round(total_char_errors / max(1, total_ref_chars), 6) if verified else None,
    }
    return {
        "generated_at": now(),
        "status": "PASS" if verified and not blockers else ("NOT_READY" if not verified else "FAIL"),
        "manifest_path": str(manifest),
        "sample_count": sample_count,
        "reference_count": len(entries),
        "verified_reference_count": len(verified),
        "reference_transcript_coverage": coverage,
        "quality_metrics": metrics,
        "sample_evaluations": evaluations,
        "blockers": blockers,
    }
