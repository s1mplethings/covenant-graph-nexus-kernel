from __future__ import annotations

import local_media_adapter
import pathlib
import stages
import user_media_pipeline_contract


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
    input_candidate = pathlib.Path(input_path)
    use_user_media = input_candidate.suffix.lower() != ".json"
    user_media_contract = {}
    pipeline_input = input_path
    if use_user_media:
        user_media_contract = user_media_pipeline_contract.prepare_user_media_pipeline(
            project_dir=root,
            input_path=input_candidate,
            output_dir=root,
        )
        if user_media_contract.get("status") != "PASS":
            return {"status": "FAIL", "mode": "local_user_media_contract", "user_media_contract": user_media_contract, "not_delivery_evidence": True}
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
    return {"status": "degraded", "mode": "local_user_media_contract" if use_user_media else "local_fixture_processing", "capability_manifest": "capability_manifest.json", "media_manifest": "media_manifest.json" if use_user_media else "", "user_media_contract": user_media_contract, "selected_adapter": capability.get("selected_adapter"), "artifacts": written, "not_real_ai_model": True, "not_delivery_evidence": True}
