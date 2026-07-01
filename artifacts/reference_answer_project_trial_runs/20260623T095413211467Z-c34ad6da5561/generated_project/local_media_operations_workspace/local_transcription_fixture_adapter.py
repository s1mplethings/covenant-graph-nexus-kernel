from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone

try:
    import local_media_adapter
except ModuleNotFoundError:  # pragma: no cover - package import path
    SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    import local_media_adapter


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_transcript(input_path: pathlib.Path, output_path: pathlib.Path) -> dict:
    metadata = local_media_adapter.read_wave_metadata(input_path)
    record = local_media_adapter.file_record(input_path)
    text = f"Local fixture transcript generated from {input_path.name}. This is not production ASR."
    return {
        "stage": "transcription",
        "status": "verified",
        "adapter": "local_transcription_fixture_adapter",
        "input_path": str(input_path),
        "output_path": str(output_path),
        "created_at": now(),
        "segments": [
            {
                "id": "fixture_segment_001",
                "start": 0,
                "end": metadata.get("duration_seconds", 0),
                "text": text,
                "not_production_asr": True,
            }
        ],
        "text": text,
        "degraded": True,
        "not_production_asr": True,
        "evidence": [
            {"input_sha256": record["sha256"], "input_size": record["size"]},
            {"wave_metadata": metadata},
            "command-backed local fixture adapter; no model or cloud service used",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    input_path = pathlib.Path(args.input)
    output_path = pathlib.Path(args.output)
    if not input_path.exists():
        print(f"input missing: {input_path}", file=sys.stderr)
        return 2
    output_path.parent.mkdir(parents=True, exist_ok=True)
    transcript = build_transcript(input_path, output_path)
    output_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(output_path), "not_production_asr": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
