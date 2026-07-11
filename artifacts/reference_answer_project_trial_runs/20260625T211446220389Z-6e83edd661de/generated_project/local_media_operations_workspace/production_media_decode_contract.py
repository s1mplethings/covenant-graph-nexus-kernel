from __future__ import annotations

import argparse
import json
import pathlib
from datetime import datetime, timezone
from typing import Any

try:
    import local_media_adapter
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import local_media_adapter


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _empty_record(path: pathlib.Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": "", "size": 0}


def _duration(path: pathlib.Path) -> float:
    if path.suffix.lower() == ".wav" and path.exists() and path.stat().st_size > 0:
        try:
            return float(local_media_adapter.read_wave_metadata(path).get("duration_seconds", 0.0))
        except Exception:
            return 0.0
    return 0.0


def media_decode_artifact(
    *,
    status: str,
    adapter: str,
    input_path: pathlib.Path,
    output_path: pathlib.Path,
    artifact_path: pathlib.Path,
    command: list[str],
    returncode: int | None,
    timed_out: bool,
    evidence: list[Any],
    blockers: list[str] | None = None,
) -> dict[str, Any]:
    record = local_media_adapter.file_record(output_path) if output_path.exists() and output_path.is_file() else _empty_record(output_path)
    duration_seconds = _duration(output_path)
    item = {
        "id": output_path.stem,
        "path": str(output_path),
        "sha256": record["sha256"],
        "size": record["size"],
        "duration_seconds": duration_seconds,
    }
    return {
        "stage": "media_decode",
        "status": status,
        "adapter": adapter,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "artifact_path": str(artifact_path),
        "created_at": now(),
        "upstream_artifacts": [],
        "items": [item] if record["size"] > 0 else [],
        "count": 1 if record["size"] > 0 else 0,
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "sha256": record["sha256"],
        "size": record["size"],
        "duration_seconds": duration_seconds,
        "evidence": evidence,
        "blockers": blockers or [],
        "commercial_ready": False,
        "not_transcription": True,
    }


def run_media_decode(
    *,
    project_dir: pathlib.Path,
    input_path: pathlib.Path,
    output_dir: pathlib.Path | None = None,
    output_path: pathlib.Path | None = None,
    artifact_path: pathlib.Path | None = None,
    timeout: float = 2.0,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    output_root = pathlib.Path(output_dir or project)
    output_root.mkdir(parents=True, exist_ok=True)
    source = pathlib.Path(input_path)
    if not source.is_absolute():
        source = (project / source).resolve()
    output = pathlib.Path(output_path or output_root / "media_decode_output.wav")
    artifact = pathlib.Path(artifact_path or output_root / "media_decode_artifact.json")
    ffmpeg = local_media_adapter.detect_tool("ffmpeg", timeout=timeout)
    if ffmpeg.get("status") != "local_tool_verified":
        doc = media_decode_artifact(
            status="unavailable",
            adapter="none",
            input_path=source,
            output_path=output,
            artifact_path=artifact,
            command=["ffmpeg", str(source), str(output)],
            returncode=None,
            timed_out=bool(ffmpeg.get("timed_out")),
            evidence=[ffmpeg],
            blockers=["media_decode_unavailable"],
        )
        write_json(artifact, doc)
        return doc
    executable = str(ffmpeg.get("path") or "ffmpeg")
    command = [
        executable,
        "-y",
        "-v",
        "error",
        "-i",
        str(source),
        "-t",
        "0.20",
        "-ac",
        "1",
        "-ar",
        "8000",
        str(output),
    ]
    run = local_media_adapter.run_bounded(command, timeout=timeout)
    blockers: list[str] = []
    if run.get("timed_out"):
        blockers.append("media_decode_timeout")
    if run.get("returncode") != 0:
        blockers.append("media_decode_returncode_nonzero")
    if not output.exists() or not output.is_file() or output.stat().st_size <= 0:
        blockers.append("media_decode_output_empty_or_missing")
    status = "verified" if not blockers else "failed"
    doc = media_decode_artifact(
        status=status,
        adapter="ffmpeg",
        input_path=source,
        output_path=output,
        artifact_path=artifact,
        command=command,
        returncode=run.get("returncode"),
        timed_out=bool(run.get("timed_out")),
        evidence=[ffmpeg, run],
        blockers=blockers,
    )
    write_json(artifact, doc)
    return doc


def capability_section(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": doc.get("status", "not_attempted"),
        "tool": doc.get("adapter", "none") if doc.get("adapter") == "ffmpeg" else "none",
        "version": "",
        "command": doc.get("command", []),
        "returncode": doc.get("returncode"),
        "timed_out": bool(doc.get("timed_out")),
        "artifact_path": pathlib.Path(str(doc.get("artifact_path", "media_decode_artifact.json"))).name,
        "output_path": pathlib.Path(str(doc.get("output_path", "media_decode_output.wav"))).name,
        "sha256": doc.get("sha256", ""),
        "size": doc.get("size", 0),
        "duration_seconds": doc.get("duration_seconds", 0),
        "evidence": doc.get("evidence", []),
        "commercial_ready": False,
        "reason": "Bounded local media decode evidence is not ASR and does not imply production readiness.",
    }


def not_attempted_section() -> dict[str, Any]:
    return {
        "status": "not_attempted",
        "tool": "none",
        "version": "",
        "command": [],
        "returncode": None,
        "timed_out": False,
        "artifact_path": "",
        "output_path": "",
        "sha256": "",
        "size": 0,
        "duration_seconds": 0,
        "evidence": ["media decode is only attempted for real user media input"],
        "commercial_ready": False,
        "reason": "No real user media input was provided for decode smoke.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()
    result = run_media_decode(
        project_dir=pathlib.Path(args.project_dir),
        input_path=pathlib.Path(args.input),
        output_dir=pathlib.Path(args.output_dir) if args.output_dir else None,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"verified", "unavailable", "not_attempted"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
