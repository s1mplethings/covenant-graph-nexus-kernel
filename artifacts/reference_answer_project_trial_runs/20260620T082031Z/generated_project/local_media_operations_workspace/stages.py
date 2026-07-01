from __future__ import annotations

import hashlib
import json
import pathlib
from datetime import datetime, timezone


PIPELINE_STAGES = ['ingest_video', 'extract_audio', 'chunk_audio', 'transcribe_audio', 'analyze_segments', 'select_segments', 'render_clips', 'export_results']


def _read_json(path: pathlib.Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _fixture_path(input_path: str, output_dir: pathlib.Path) -> pathlib.Path:
    raw = pathlib.Path(input_path)
    if raw.exists():
        return raw
    candidate = output_dir / input_path
    if candidate.exists():
        return candidate
    return output_dir / "fixtures" / "media_fixture.json"


def _file_item(path: pathlib.Path, kind: str) -> dict:
    return {
        "id": path.stem,
        "kind": kind,
        "path": str(path),
        "size": path.stat().st_size if path.exists() else 0,
        "sha256": _sha256(path) if path.exists() else "",
    }


def _fixture_items(fixture: dict, fixture_root: pathlib.Path) -> list[dict]:
    items = []
    for entry in fixture.get("files", []):
        if not isinstance(entry, dict):
            continue
        path = fixture_root / str(entry.get("path", ""))
        item = _file_item(path, str(entry.get("kind", "asset")))
        item.update({"label": entry.get("label", ""), "duration_seconds": entry.get("duration_seconds", 0)})
        items.append(item)
    return items


def _stage_items(stage: str, fixture: dict, fixture_root: pathlib.Path, upstream_doc: dict) -> list[dict]:
    files = _fixture_items(fixture, fixture_root)
    segments = [item for item in fixture.get("segments", []) if isinstance(item, dict)]
    if stage == "ingest_video":
        return files
    if stage == "extract_audio":
        return [
            {"id": f"audio_{index + 1}", "source_id": item.get("id"), "kind": "audio_track", "duration_seconds": item.get("duration_seconds", 0)}
            for index, item in enumerate(files)
            if item.get("kind") in {"video", "audio"}
        ]
    if stage == "chunk_audio":
        return [
            {"id": str(segment.get("id", f"segment_{index + 1}")), "start": segment.get("start", 0), "end": segment.get("end", 0), "text": segment.get("text", "")}
            for index, segment in enumerate(segments)
        ]
    if stage == "transcribe_audio":
        source = upstream_doc.get("items") or segments
        return [
            {"id": item.get("id", f"transcript_{index + 1}"), "text": item.get("text", ""), "confidence": 1.0, "source_stage": upstream_doc.get("stage", "")}
            for index, item in enumerate(source)
        ]
    if stage == "analyze_segments":
        source = upstream_doc.get("items") or segments
        keywords = [str(item).lower() for item in fixture.get("candidate_keywords", [])]
        analyzed = []
        for index, item in enumerate(source):
            text = str(item.get("text", ""))
            score = sum(1 for keyword in keywords if keyword and keyword in text.lower())
            analyzed.append({"id": item.get("id", f"analysis_{index + 1}"), "text": text, "score": score, "candidate": score > 0, "reasons": [keyword for keyword in keywords if keyword in text.lower()]})
        return analyzed
    if stage == "select_segments":
        return [item for item in upstream_doc.get("items", []) if item.get("candidate")]
    if stage == "render_clips":
        return [
            {"id": f"clip_{index + 1}", "source_segment_id": item.get("id"), "render_status": "degraded_fixture_clip", "text": item.get("text", "")}
            for index, item in enumerate(upstream_doc.get("items", []))
        ]
    if stage == "export_results":
        return [
            {"id": "export_package", "clip_count": len(upstream_doc.get("items", [])), "report": "fixture processing report", "not_real_ai_model": True}
        ]
    return upstream_doc.get("items", [])


def run_stage(stage: str, artifact_name: str, input_path: str, output_dir: pathlib.Path, upstream_artifact: str = "") -> dict:
    """Write an honest degraded local-fixture stage artifact with schema and traceability."""
    output_path = output_dir / artifact_name
    upstream_artifacts = [upstream_artifact] if upstream_artifact else []
    fixture_path = _fixture_path(input_path, output_dir)
    fixture = _read_json(fixture_path)
    fixture_root = fixture_path.parent
    upstream_doc = _read_json(output_dir / upstream_artifact) if upstream_artifact else {}
    items = _stage_items(stage, fixture, fixture_root, upstream_doc)
    artifact = {
        "stage": stage,
        "status": "degraded",
        "mode": "local_fixture_processing",
        "count": len(items),
        "input_path": str(fixture_path if not upstream_artifact else output_dir / upstream_artifact),
        "output_path": str(output_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "upstream_artifacts": upstream_artifacts,
        "items": items,
        "known_gaps": ["local fixture processing only; no real AI model or cloud processing claimed"],
        "fixture_path": str(fixture_path),
        "not_real_ai_model": True,
        "not_delivery_evidence": True,
    }
    output_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact
