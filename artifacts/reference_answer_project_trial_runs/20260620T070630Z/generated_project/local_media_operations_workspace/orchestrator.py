from __future__ import annotations

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


def run(input_path: str = "input.mp4", output_dir: str = ".") -> dict:
    """Run the shared degraded pipeline and return artifact paths."""
    root = pathlib.Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    previous = ""
    written = []
    for stage_name, artifact_name in PIPELINE:
        artifact = stages.run_stage(stage_name, artifact_name, input_path, root, previous)
        previous = artifact["output_path"]
        written.append(artifact["output_path"])
    return {"status": "degraded", "artifacts": written, "not_delivery_evidence": True}
