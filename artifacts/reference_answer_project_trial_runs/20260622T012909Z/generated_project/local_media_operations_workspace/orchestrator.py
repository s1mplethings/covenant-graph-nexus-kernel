from __future__ import annotations

import local_media_adapter
import pathlib
import stages


PIPELINE = [
    ("ingest_video", "stage_plan.json"),
    ("extract_audio", "media_manifest.json"),
    ("chunk_audio", "audio_chunk_manifest.json"),
    ("transcribe_audio", "transcript_merged.json"),
    ("analyze_segments", "segment_analysis.json"),
    ("select_segments", "selected_segments.json"),
    ("render_clips", "clip_manifest.json"),
    ("export_results", "export_results.json"),
]


def run(input_path: str = "fixtures/media_fixture.json", output_dir: str = ".") -> dict:
    """Run the shared local fixture pipeline and return artifact paths."""
    root = pathlib.Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    capability = local_media_adapter.build_capability_manifest(root)
    previous = ""
    written = []
    for stage_name, artifact_name in PIPELINE:
        artifact = stages.run_stage(stage_name, artifact_name, input_path, root, previous)
        previous = artifact["output_path"]
        written.append(artifact["output_path"])
    return {"status": "degraded", "mode": "local_fixture_processing", "capability_manifest": "capability_manifest.json", "selected_adapter": capability.get("selected_adapter"), "artifacts": written, "not_real_ai_model": True, "not_delivery_evidence": True}
