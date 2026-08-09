#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
from datetime import datetime, timezone
from typing import Any

import local_media_adapter
import local_model_adapter
import local_transcription_fixture_adapter
import production_media_decode_contract
import real_asr_adapter_contract
import asr_evidence_tier
import asr_quality_gate
import real_asr_multi_sample_eval
import asr_reference_transcript_eval
import commercial_promotion_gate
import production_reliability_gate
import commercial_ready_gate
import user_media_pipeline_contract


DEFAULT_STAGES = [
    "ingest_video",
    "extract_audio",
    "chunk_audio",
    "transcribe_audio",
    "analyze_segments",
    "select_segments",
    "render_clips",
    "export_results",
]

DEFAULT_ARTIFACTS = [
    "stage_plan.json",
    "media_manifest.json",
    "audio_chunk_manifest.json",
    "transcript_merged.json",
    "segment_analysis.json",
    "selected_segments.json",
    "clip_manifest.json",
    "export_results.json",
]


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def contract(run_dir: pathlib.Path) -> dict[str, Any]:
    return read_json(pathlib.Path(run_dir) / "discovery" / "complexity_project_contract.json")


def list_from_contract(doc: dict[str, Any], key: str, fallback: list[str]) -> list[str]:
    raw = doc.get(key)
    if isinstance(raw, list):
        values = [str(item).strip() for item in raw if str(item).strip()]
        if values:
            return values
    return list(fallback)


def stage_artifact_pairs(stages: list[str], artifacts: list[str]) -> list[tuple[str, str]]:
    """Map stable artifact contracts to their semantic producer across stage-name revisions."""
    aliases = {
        "stage_plan.json": ("plan_pipeline", "ingest_video"),
        "media_manifest.json": ("ingest_video",),
        "audio_chunk_manifest.json": ("build_audio_chunk_manifest", "chunk_audio", "extract_audio"),
        "transcript_merged.json": ("merge_transcript", "transcribe_chunks", "transcribe_audio"),
        "segment_analysis.json": ("optional_analysis", "analyze_segments"),
        "selected_segments.json": ("select_segments",),
        "clip_manifest.json": ("build_clip_manifest", "render_clips", "render_clips_batch"),
        "export_results.json": ("export_results",),
    }
    available = set(stages)
    pairs: list[tuple[str, str]] = []
    for index, artifact in enumerate(artifacts):
        preferred = aliases.get(artifact, ())
        stage = next((name for name in preferred if name in available), "")
        if not stage:
            stage = stages[min(index, len(stages) - 1)] if stages else f"stage_{index + 1}"
        pairs.append((stage, artifact))
    return pairs


def write_core(project_dir: pathlib.Path, stages: list[str], artifacts: list[str]) -> None:
    stage_pairs = ",\n    ".join(
        f'("{stage}", "{artifact}")' for stage, artifact in stage_artifact_pairs(stages, artifacts)
    )
    orchestrator = f'''from __future__ import annotations

import local_media_adapter
import pathlib
import stages
import user_media_pipeline_contract


PIPELINE = [
    {stage_pairs},
]


def run(input_path: str = "fixtures/media_fixture.json", output_dir: str = ".") -> dict:
    """Run the shared local fixture pipeline and return artifact paths."""
    root = pathlib.Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    input_candidate = pathlib.Path(input_path)
    use_user_media = input_candidate.suffix.lower() != ".json"
    user_media_contract = {{}}
    pipeline_input = input_path
    if use_user_media:
        user_media_contract = user_media_pipeline_contract.prepare_user_media_pipeline(
            project_dir=root,
            input_path=input_candidate,
            output_dir=root,
        )
        if user_media_contract.get("status") != "PASS":
            return {{"status": "FAIL", "mode": "local_user_media_contract", "user_media_contract": user_media_contract, "not_delivery_evidence": True}}
        pipeline_input = user_media_contract.get("fixture_path") or input_path
        capability = local_media_adapter.build_capability_manifest(root, user_media_path=input_candidate)
    else:
        capability = local_media_adapter.build_capability_manifest(root)
    previous = ""
    written = []
    for stage_name, artifact_name in PIPELINE:
        artifact = stages.run_stage(stage_name, artifact_name, pipeline_input, root, previous)
        previous = artifact["output_path"]
        written.append(artifact["output_path"])
    return {{"status": "degraded", "mode": "local_user_media_contract" if use_user_media else "local_fixture_processing", "capability_manifest": "capability_manifest.json", "media_manifest": "media_manifest.json" if use_user_media else "", "user_media_contract": user_media_contract, "selected_adapter": capability.get("selected_adapter"), "artifacts": written, "not_real_ai_model": True, "not_delivery_evidence": True}}
'''
    stage_names = ", ".join(repr(stage) for stage in stages)
    stages_py = f'''from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone


PIPELINE_STAGES = [{stage_names}]


def _read_json(path: pathlib.Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {{}}
    return doc if isinstance(doc, dict) else {{}}


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _fixture_file_path(fixture_root: pathlib.Path, raw_path: str, *, allow_absolute: bool = False) -> pathlib.Path:
    root = fixture_root.resolve()
    raw = pathlib.Path(raw_path)
    candidate = raw.resolve() if raw.is_absolute() else (fixture_root / raw_path).resolve()
    if allow_absolute and raw.is_absolute():
        return candidate
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("fixture_validation_failed:path_outside_fixture_dir:" + raw_path) from exc
    return candidate


def _validate_fixture(fixture: dict, fixture_root: pathlib.Path) -> None:
    blockers = []
    if fixture.get("kind") != "CGKNLocalMediaFixture":
        blockers.append("kind_mismatch")
    files = fixture.get("files")
    if not isinstance(files, list) or not files:
        blockers.append("files_missing")
        files = []
    for index, entry in enumerate(files):
        if not isinstance(entry, dict):
            blockers.append("file_entry_not_object:" + str(index))
            continue
        rel = str(entry.get("path", "")).strip()
        if not rel:
            blockers.append("file_path_missing:" + str(index))
            continue
        try:
            path = _fixture_file_path(fixture_root, rel, allow_absolute=bool(entry.get("real_user_media_input")))
        except ValueError as exc:
            blockers.append(str(exc).replace("fixture_validation_failed:", "", 1))
            continue
        if not path.exists() or not path.is_file():
            blockers.append("file_missing:" + rel)
            continue
        declared_size = entry.get("size")
        if declared_size not in (None, ""):
            try:
                if int(declared_size) != path.stat().st_size:
                    blockers.append("size_mismatch:" + rel)
            except Exception:
                blockers.append("size_invalid:" + rel)
        declared_sha = str(entry.get("sha256", "")).strip()
        if declared_sha and declared_sha != _sha256(path):
            blockers.append("sha256_mismatch:" + rel)
    if not isinstance(fixture.get("segments"), list) or not fixture.get("segments"):
        blockers.append("segments_missing")
    if not isinstance(fixture.get("candidate_keywords"), list) or not fixture.get("candidate_keywords"):
        blockers.append("candidate_keywords_missing")
    if blockers:
        raise ValueError("fixture_validation_failed:" + ",".join(blockers))


def _fixture_path(input_path: str, output_dir: pathlib.Path) -> pathlib.Path:
    raw = pathlib.Path(input_path)
    if raw.exists():
        return raw
    candidate = output_dir / input_path
    if candidate.exists():
        return candidate
    return output_dir / "fixtures" / "media_fixture.json"


def _file_item(path: pathlib.Path, kind: str) -> dict:
    return {{
        "id": path.stem,
        "kind": kind,
        "path": str(path),
        "size": path.stat().st_size if path.exists() else 0,
        "sha256": _sha256(path) if path.exists() else "",
    }}


def _fixture_items(fixture: dict, fixture_root: pathlib.Path) -> list[dict]:
    items = []
    for entry in fixture.get("files", []):
        if not isinstance(entry, dict):
            continue
        path = _fixture_file_path(fixture_root, str(entry.get("path", "")), allow_absolute=bool(entry.get("real_user_media_input")))
        item = _file_item(path, str(entry.get("kind", "asset")))
        item.update({{"label": entry.get("label", ""), "duration_seconds": entry.get("duration_seconds", 0)}})
        items.append(item)
    return items


def _stage_items(stage: str, fixture: dict, fixture_root: pathlib.Path, upstream_doc: dict) -> list[dict]:
    files = _fixture_items(fixture, fixture_root)
    segments = [item for item in fixture.get("segments", []) if isinstance(item, dict)]
    if stage == "ingest_video":
        return files
    if stage == "extract_audio":
        return [
            {{"id": f"audio_{{index + 1}}", "source_id": item.get("id"), "kind": "audio_track", "duration_seconds": item.get("duration_seconds", 0)}}
            for index, item in enumerate(files)
            if item.get("kind") in {{"video", "audio"}}
        ]
    if stage in {{"chunk_audio", "build_audio_chunk_manifest"}}:
        return [
            {{"id": str(segment.get("id", f"segment_{{index + 1}}")), "start": segment.get("start", 0), "end": segment.get("end", 0), "text": segment.get("text", "")}}
            for index, segment in enumerate(segments)
        ]
    if stage in {{"transcribe_audio", "transcribe_chunks", "merge_transcript"}}:
        source = upstream_doc.get("items") or segments
        return [
            {{"id": item.get("id", f"transcript_{{index + 1}}"), "text": item.get("text", ""), "confidence": 1.0, "source_stage": upstream_doc.get("stage", "")}}
            for index, item in enumerate(source)
        ]
    if stage in {{"analyze_segments", "optional_analysis"}}:
        source = upstream_doc.get("items") or segments
        keywords = [str(item).lower() for item in fixture.get("candidate_keywords", [])]
        analyzed = []
        for index, item in enumerate(source):
            text = str(item.get("text", ""))
            score = sum(1 for keyword in keywords if keyword and keyword in text.lower())
            analyzed.append({{"id": item.get("id", f"analysis_{{index + 1}}"), "text": text, "score": score, "candidate": score > 0, "reasons": [keyword for keyword in keywords if keyword in text.lower()]}})
        return analyzed
    if stage == "select_segments":
        return [item for item in upstream_doc.get("items", []) if item.get("candidate")]
    if stage in {{"render_clips", "build_clip_manifest", "render_clips_batch"}}:
        return [
            {{"id": f"clip_{{index + 1}}", "source_segment_id": item.get("id"), "render_status": "degraded_fixture_clip", "text": item.get("text", "")}}
            for index, item in enumerate(upstream_doc.get("items", []))
        ]
    if stage == "export_results":
        return [
            {{"id": "export_package", "clip_count": len(upstream_doc.get("items", [])), "report": "fixture processing report", "not_real_ai_model": True}}
        ]
    return upstream_doc.get("items", [])


def run_stage(stage: str, artifact_name: str, input_path: str, output_dir: pathlib.Path, upstream_artifact: str = "") -> dict:
    """Write an honest degraded local-fixture stage artifact with schema and traceability."""
    output_path = output_dir / artifact_name
    upstream_artifacts = [upstream_artifact] if upstream_artifact else []
    fixture_path = _fixture_path(input_path, output_dir)
    fixture = _read_json(fixture_path)
    fixture_root = fixture_path.parent
    _validate_fixture(fixture, fixture_root)
    upstream_doc = _read_json(output_dir / upstream_artifact) if upstream_artifact else {{}}
    items = _stage_items(stage, fixture, fixture_root, upstream_doc)
    artifact = {{
        "stage": stage,
        "status": "degraded",
        "mode": "local_fixture_processing",
        "count": len(items),
        "input_path": str(fixture_path if not upstream_artifact else output_dir / upstream_artifact),
        "output_path": str(output_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "upstream_artifacts": upstream_artifacts,
        "items": items,
        "evidence": [
            {{"fixture_path": str(fixture_path)}},
            {{"user_media_contract": bool(fixture.get("user_media_contract"))}},
            {{"upstream_artifacts": upstream_artifacts}},
        ],
        "known_gaps": ["local fixture processing only; no real AI model or cloud processing claimed"],
        "fixture_path": str(fixture_path),
        "not_real_ai_model": True,
        "not_delivery_evidence": True,
    }}
    if fixture.get("user_media_contract"):
        artifact.update({{
            "mode": "local_user_media_contract",
            "real_user_media_input": True,
            "original_input_path": fixture.get("original_input_path", ""),
            "safe_input_path": fixture.get("safe_input_path", ""),
            "file_type": fixture.get("file_type", ""),
            "size": fixture.get("size", 0),
            "sha256": fixture.get("sha256", ""),
            "metadata_status": fixture.get("metadata_status", ""),
            "adapter_status": fixture.get("adapter_status", ""),
        }})
    output_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
    return artifact
'''
    cli = '''from __future__ import annotations

import argparse
import orchestrator


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="fixtures/media_fixture.json")
    parser.add_argument("--output-dir", default=".")
    args = parser.parse_args()
    result = orchestrator.run(input_path=args.input, output_dir=args.output_dir)
    print(result)
    return 0 if result.get("status") != "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
'''
    gui = '''from __future__ import annotations

import tkinter as tk
import orchestrator


def build_app() -> tk.Tk:
    root = tk.Tk()
    root.title("CGKN Degraded Pipeline")
    label = tk.Label(root, text="Shared orchestrator/stages pipeline. Delivery evidence is still required.")
    label.pack()
    button = tk.Button(root, text="Run degraded pipeline", command=lambda: orchestrator.run())
    button.pack()
    return root


if __name__ == "__main__":
    build_app().mainloop()
'''
    (project_dir / "orchestrator.py").write_text(orchestrator, encoding="utf-8")
    (project_dir / "stages.py").write_text(stages_py, encoding="utf-8")
    (project_dir / "cli.py").write_text(cli, encoding="utf-8")
    (project_dir / "gui_app.py").write_text(gui, encoding="utf-8")
    (project_dir / "local_media_adapter.py").write_text(
        pathlib.Path(local_media_adapter.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (project_dir / "local_model_adapter.py").write_text(
        pathlib.Path(local_model_adapter.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (project_dir / "local_transcription_fixture_adapter.py").write_text(
        pathlib.Path(local_transcription_fixture_adapter.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (project_dir / "production_media_decode_contract.py").write_text(
        pathlib.Path(production_media_decode_contract.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (project_dir / "real_asr_adapter_contract.py").write_text(
        pathlib.Path(real_asr_adapter_contract.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (project_dir / "asr_evidence_tier.py").write_text(
        pathlib.Path(asr_evidence_tier.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (project_dir / "asr_quality_gate.py").write_text(
        pathlib.Path(asr_quality_gate.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (project_dir / "real_asr_multi_sample_eval.py").write_text(
        pathlib.Path(real_asr_multi_sample_eval.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (project_dir / "asr_reference_transcript_eval.py").write_text(
        pathlib.Path(asr_reference_transcript_eval.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (project_dir / "commercial_promotion_gate.py").write_text(
        pathlib.Path(commercial_promotion_gate.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (project_dir / "production_reliability_gate.py").write_text(
        pathlib.Path(production_reliability_gate.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (project_dir / "commercial_ready_gate.py").write_text(
        pathlib.Path(commercial_ready_gate.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (project_dir / "user_media_pipeline_contract.py").write_text(
        pathlib.Path(user_media_pipeline_contract.__file__).read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def write_fixture_files(project_dir: pathlib.Path) -> dict[str, Any]:
    fixture_dir = project_dir / "fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    wav_path = fixture_dir / "sample_audio.wav"
    wav_record = local_media_adapter.create_tiny_wav(wav_path)
    files = {
        "sample_video.txt": "00:00 intro: project overview\n00:06 candidate moment: useful quote about local editing\n00:14 outro: export reminder\n",
        "sample_audio.txt": "intro tone\ncandidate highlight about review workflow\nexport cue\n",
        "asset_notes.txt": "thumbnail, lower-third, and caption assets for local fixture processing\n",
    }
    file_entries: list[dict[str, Any]] = []
    for name, content in files.items():
        path = fixture_dir / name
        path.write_text(content, encoding="utf-8")
        file_entries.append(
            {
                "path": name,
                "kind": "video" if "video" in name else ("audio" if "audio" in name else "asset"),
                "label": name.replace("_", " ").replace(".txt", ""),
                "duration_seconds": 18 if "video" in name else (12 if "audio" in name else 0),
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    wav_metadata = local_media_adapter.read_wave_metadata(wav_path)
    file_entries.append(
        {
            "path": wav_path.name,
            "kind": "audio",
            "label": "sample audio wav",
            "duration_seconds": wav_metadata["duration_seconds"],
            "framerate": wav_metadata["framerate"],
            "channels": wav_metadata["channels"],
            "sample_width": wav_metadata["sample_width"],
            "size": wav_record["size"],
            "sha256": wav_record["sha256"],
            "real_media_fixture": True,
        }
    )
    fixture = {
        "kind": "CGKNLocalMediaFixture",
        "description": "Small local fake-media fixture for deterministic pipeline smoke runs.",
        "files": file_entries,
        "candidate_keywords": ["candidate", "highlight", "export", "review"],
        "segments": [
            {"id": "seg_001", "start": 0, "end": 6, "text": "intro project overview"},
            {"id": "seg_002", "start": 6, "end": 14, "text": "candidate highlight about local review workflow"},
            {"id": "seg_003", "start": 14, "end": 18, "text": "export reminder for selected outputs"},
        ],
        "not_real_ai_model": True,
    }
    (fixture_dir / "media_fixture.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"fixture": "fixtures/media_fixture.json", "files": [f"fixtures/{name}" for name in files] + ["fixtures/sample_audio.wav"]}


def write_stage_artifacts(project_dir: pathlib.Path, stages: list[str], artifacts: list[str]) -> list[str]:
    written: list[str] = []
    previous = ""
    for stage, artifact_name in stage_artifact_pairs(stages, artifacts):
        path = project_dir / artifact_name
        doc = {
            "stage": stage,
            "status": "degraded",
            "count": 0,
            "input_path": previous or "input.mp4",
            "output_path": str(path),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "upstream_artifacts": [previous] if previous else [],
            "items": [],
            "known_gaps": ["deterministic structure only; no real media processing claimed"],
            "not_delivery_evidence": True,
        }
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(artifact_name)
        previous = artifact_name
    return written


def materialize(*, project_dir: pathlib.Path, run_dir: pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    project.mkdir(parents=True, exist_ok=True)
    doc = contract(pathlib.Path(run_dir))
    stages = list_from_contract(doc, "required_pipeline_stages", DEFAULT_STAGES)
    artifacts = list_from_contract(doc, "required_stage_artifacts", DEFAULT_ARTIFACTS)
    write_core(project, stages, artifacts)
    fixture_manifest = write_fixture_files(project)
    written_artifacts = write_stage_artifacts(project, stages, artifacts)
    manifest = {
        "status": "PASS",
        "mode": "deterministic_degraded_structure",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_dir": str(project),
        "run_dir": str(run_dir),
        "core_files": ["orchestrator.py", "stages.py", "cli.py", "gui_app.py", "local_media_adapter.py", "local_model_adapter.py", "local_transcription_fixture_adapter.py", "production_media_decode_contract.py", "real_asr_adapter_contract.py", "asr_evidence_tier.py", "asr_quality_gate.py", "real_asr_multi_sample_eval.py", "asr_reference_transcript_eval.py", "commercial_promotion_gate.py", "production_reliability_gate.py", "commercial_ready_gate.py", "user_media_pipeline_contract.py"],
        "fixture_processing": fixture_manifest,
        "stage_artifacts": written_artifacts,
        "not_delivery_evidence": True,
    }
    (project / "implementation_structure_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    result = materialize(project_dir=pathlib.Path(args.project_dir), run_dir=pathlib.Path(args.run_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
