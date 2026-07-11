from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import shutil
import struct
import subprocess
import time
import wave
from datetime import datetime, timezone
from typing import Any

try:
    import local_model_adapter
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import local_model_adapter

try:
    import production_media_decode_contract
except (ImportError, ModuleNotFoundError):  # pragma: no cover - package import path
    from scripts import production_media_decode_contract


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def create_tiny_wav(path: pathlib.Path, *, duration_seconds: float = 0.25, framerate: int = 8000) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = max(1, int(duration_seconds * framerate))
    amplitude = 6000
    frequency = 440.0
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(framerate)
        for index in range(frame_count):
            sample = int(amplitude * math.sin(2 * math.pi * frequency * (index / framerate)))
            handle.writeframesraw(struct.pack("<h", sample))
    return file_record(path) | {"type": "wav"}


def file_record(path: pathlib.Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256(path),
        "size": path.stat().st_size,
    }


def read_wave_metadata(path: pathlib.Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        framerate = handle.getframerate()
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
    duration = frames / framerate if framerate else 0.0
    return {
        "frames": frames,
        "framerate": framerate,
        "channels": channels,
        "sample_width": sample_width,
        "duration_seconds": round(duration, 6),
    }


def run_bounded(command: list[str], *, timeout: float = 2.0) -> dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        return {
            "command": command,
            "returncode": proc.returncode,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": proc.stdout[:4000],
            "stderr": proc.stderr[:4000],
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": None,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": str(exc.stdout or "")[:4000],
            "stderr": str(exc.stderr or "")[:4000],
            "timed_out": True,
        }
    except Exception as exc:
        return {
            "command": command,
            "returncode": None,
            "duration_seconds": round(time.time() - started, 3),
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
        }


def detect_tool(name: str, *, timeout: float = 2.0) -> dict[str, Any]:
    executable = shutil.which(name)
    if not executable:
        return {
            "status": "local_tool_unavailable",
            "tool": name,
            "path": "",
            "version": "",
            "command": [name, "-version"],
            "returncode": None,
            "evidence": [f"{name} not found on PATH"],
        }
    result = run_bounded([executable, "-version"], timeout=timeout)
    first_line = (result.get("stdout") or result.get("stderr") or "").splitlines()
    return {
        "status": "local_tool_verified" if result.get("returncode") == 0 and not result.get("timed_out") else "local_tool_unavailable",
        "tool": name,
        "path": executable,
        "version": first_line[0] if first_line else "",
        "command": result["command"],
        "returncode": result.get("returncode"),
        "evidence": [line for line in first_line[:3] if line] or [str(result.get("stderr") or "")[:300]],
        "timed_out": result.get("timed_out", False),
    }


def inspect_with_ffprobe(path: pathlib.Path, *, timeout: float = 2.0) -> dict[str, Any]:
    executable = shutil.which("ffprobe")
    if not executable:
        return {
            "status": "local_tool_unavailable",
            "tool": "ffprobe",
            "version": "",
            "command": ["ffprobe", str(path)],
            "returncode": None,
            "evidence": ["ffprobe not found on PATH"],
        }
    command = [
        executable,
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,codec_name,sample_rate,channels,duration",
        "-of",
        "json",
        str(path),
    ]
    result = run_bounded(command, timeout=timeout)
    version = detect_tool("ffprobe", timeout=timeout)
    evidence = []
    if result.get("stdout"):
        evidence.append(str(result["stdout"])[:1000])
    if result.get("stderr"):
        evidence.append(str(result["stderr"])[:1000])
    return {
        "status": "local_tool_verified" if result.get("returncode") == 0 and not result.get("timed_out") else "local_tool_unavailable",
        "tool": "ffprobe",
        "version": version.get("version", ""),
        "command": command,
        "returncode": result.get("returncode"),
        "evidence": evidence or ["ffprobe produced no metadata evidence"],
        "timed_out": result.get("timed_out", False),
    }


def build_capability_manifest(
    project_dir: pathlib.Path,
    *,
    fixture_path: pathlib.Path | None = None,
    user_media_path: pathlib.Path | None = None,
    output_path: pathlib.Path | None = None,
    timeout: float = 2.0,
    placeholder_transcription: bool = True,
) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    wav_path = fixture_path or project / "fixtures" / "sample_audio.wav"
    output = output_path or project / "capability_manifest.json"
    if not wav_path.exists():
        create_tiny_wav(wav_path)

    media_fixture = file_record(wav_path) | {"status": "verified", "type": "wav"}
    wave_metadata = read_wave_metadata(wav_path)
    ffprobe = inspect_with_ffprobe(wav_path, timeout=timeout)
    ffmpeg = detect_tool("ffmpeg", timeout=timeout)
    transcription_input = pathlib.Path(user_media_path) if user_media_path else wav_path
    transcription = local_model_adapter.evaluate(
        project_dir=project,
        input_path=transcription_input,
        output_path=project / "transcription_adapter_result.json",
        timeout=timeout,
        placeholder=placeholder_transcription,
    )
    user_media_input: dict[str, Any] | None = None
    media_decode = production_media_decode_contract.not_attempted_section()
    if user_media_path:
        try:
            from scripts import user_media_pipeline_contract
        except (ImportError, ModuleNotFoundError):  # pragma: no cover - generated project import path
            import user_media_pipeline_contract  # type: ignore

        user_media_result = user_media_pipeline_contract.prepare_user_media_pipeline(
            project_dir=project,
            input_path=pathlib.Path(user_media_path),
            output_dir=project,
            timeout=timeout,
        )
        manifest_path = pathlib.Path(str(user_media_result.get("media_manifest", "")))
        manifest_doc: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                manifest_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest_doc = {}
        user_media_input = {
            "status": "verified" if user_media_result.get("status") == "PASS" else "failed",
            "source": "real_user_media_input",
            "path": str(pathlib.Path(user_media_path)),
            "safe_input_path": manifest_doc.get("safe_input_path", ""),
            "file_type": manifest_doc.get("file_type", ""),
            "size": user_media_result.get("size", 0),
            "sha256": user_media_result.get("sha256", ""),
            "metadata_status": user_media_result.get("metadata_status", ""),
            "adapter_status": user_media_result.get("adapter_status", ""),
            "media_manifest": "media_manifest.json",
            "inspect_artifact": "user_media_inspect.json",
            "smoke_log": "user_media_smoke_log.json",
            "evidence": manifest_doc.get("evidence", []),
            "commercial_ready": False,
        }
        decode_doc = production_media_decode_contract.run_media_decode(
            project_dir=project,
            input_path=pathlib.Path(user_media_path),
            output_dir=project,
            timeout=timeout,
        )
        media_decode = production_media_decode_contract.capability_section(decode_doc)

    if ffprobe.get("status") == "local_tool_verified":
        selected_adapter = "local_tool_verified"
        metadata_status = "ffprobe_verified"
        metadata_tool = "ffprobe"
        metadata_version = str(ffprobe.get("version", ""))
        metadata_command = ffprobe.get("command", [])
        metadata_returncode = ffprobe.get("returncode")
        metadata_evidence = [
            {"python_wave": wave_metadata},
            {"ffprobe": ffprobe.get("evidence", [])},
        ]
    else:
        selected_adapter = "python_wave_verified"
        metadata_status = "python_wave_verified"
        metadata_tool = "python_wave"
        metadata_version = "python_standard_library_wave"
        metadata_command = "wave.open"
        metadata_returncode = 0
        metadata_evidence = [
            {"python_wave": wave_metadata},
            {"ffprobe": ffprobe.get("status"), "evidence": ffprobe.get("evidence", [])},
        ]

    audio_status = "verified" if ffmpeg.get("status") == "local_tool_verified" else "unavailable"
    adapter_statuses = [
        "fixture_degraded",
        "python_wave_verified",
        str(ffprobe.get("status", "local_tool_unavailable")),
        str(transcription.get("model_status", transcription.get("status", "local_model_unavailable"))),
        str(transcription.get("status", "local_model_unavailable")),
    ]
    if user_media_input:
        adapter_statuses.extend(
            [
                "real_user_media_input",
                str(user_media_input.get("metadata_status", "")),
                str(user_media_input.get("adapter_status", "")),
                f"media_decode_{media_decode.get('status', 'not_attempted')}",
            ]
        )
    capabilities = {
        "media_fixture": media_fixture,
        "media_metadata": {
            "status": metadata_status,
            "tool": metadata_tool,
            "version": metadata_version,
            "command": metadata_command,
            "returncode": metadata_returncode,
            "evidence": metadata_evidence,
        },
        "audio_extract": {
            "status": audio_status,
            "tool": "ffmpeg" if audio_status == "verified" else "none",
            "version": str(ffmpeg.get("version", "")),
            "command": ffmpeg.get("command", []),
            "returncode": ffmpeg.get("returncode"),
            "evidence": ffmpeg.get("evidence", []),
        },
        "media_decode": media_decode,
        "transcription": {
            "status": transcription.get("status", "local_model_unavailable"),
            "tool": transcription.get("tool", "none"),
            "model": transcription.get("model"),
            "adapter": transcription.get("adapter", ""),
            "command": transcription.get("command"),
            "returncode": transcription.get("returncode"),
            "input_artifact": transcription.get("input_artifact", ""),
            "output_artifact": transcription.get("output_artifact", ""),
            "artifact": transcription.get("artifact", {}),
            "not_production_asr": bool(transcription.get("not_production_asr")),
            "evidence": transcription.get("evidence", []),
            "commercial_ready": False,
            "reason": transcription.get("reason", "No local transcription model is bundled or claimed."),
        },
        "analysis": {
            "status": "deterministic",
            "evidence": ["Segment candidates are deterministic fixture analysis, not AI transcription."],
        },
    }
    if user_media_input:
        capabilities["user_media_input"] = user_media_input
    known_gaps = [
        "fixture_degraded: tiny local WAV fixture only",
        f"{transcription.get('status', 'local_model_unavailable')}: no production transcription model is claimed",
    ]
    if user_media_input:
        known_gaps.append("real_user_media_input: local input contract verified but not production media pipeline")
    if media_decode.get("status") == "verified":
        known_gaps.append("media_decode: bounded ffmpeg extract verified but not production media pipeline")
    elif media_decode.get("status") == "unavailable":
        known_gaps.append("media_decode: ffmpeg unavailable")
    elif media_decode.get("status") == "failed":
        known_gaps.append("media_decode: ffmpeg extract failed")
    manifest = {
        "generated_at": now(),
        "selected_adapter": selected_adapter,
        "adapter_statuses": adapter_statuses,
        "commercial_ready": False,
        "capabilities": capabilities,
        "tool_detection": {
            "ffprobe": ffprobe,
            "ffmpeg": ffmpeg,
        },
        "known_gaps": known_gaps,
        "commercial_readiness_reason": "Bounded local WAV metadata verification is useful evidence, but it is not production media processing or a real AI model.",
    }
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--fixture-path", default="")
    parser.add_argument("--user-media-path", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--timeout", type=float, default=2.0)
    args = parser.parse_args()
    manifest = build_capability_manifest(
        pathlib.Path(args.project_dir),
        fixture_path=pathlib.Path(args.fixture_path) if args.fixture_path else None,
        user_media_path=pathlib.Path(args.user_media_path) if args.user_media_path else None,
        output_path=pathlib.Path(args.output) if args.output else None,
        timeout=args.timeout,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
