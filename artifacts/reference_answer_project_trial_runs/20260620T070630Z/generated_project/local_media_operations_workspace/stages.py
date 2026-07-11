from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone


PIPELINE_STAGES = ['ingest_video', 'extract_audio', 'chunk_audio', 'transcribe_audio', 'analyze_segments', 'select_segments', 'render_clips', 'export_results']


def run_stage(stage: str, artifact_name: str, input_path: str, output_dir: pathlib.Path, upstream_artifact: str = "") -> dict:
    """Write an honest degraded stage artifact with schema and traceability."""
    output_path = output_dir / artifact_name
    upstream_artifacts = [upstream_artifact] if upstream_artifact else []
    artifact = {
        "stage": stage,
        "status": "degraded",
        "count": 0,
        "input_path": input_path if not upstream_artifact else upstream_artifact,
        "output_path": str(output_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "upstream_artifacts": upstream_artifacts,
        "items": [],
        "known_gaps": ["deterministic structure only; no real media processing claimed"],
        "not_delivery_evidence": True,
    }
    output_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact
