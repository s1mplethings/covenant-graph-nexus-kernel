from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

from contracts.status import EvidenceStatus
from scripts import canonical_evidence_hash


KIND = "CGKNCanonicalMediaValidationResult"
SCHEMA_VERSION = "1.0"
IMAGE_SUFFIXES = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP"}
VIDEO_SUFFIXES = {".mp4", ".webm"}
PLACEHOLDER_TOKENS = ("placeholder", "mock", "fallback", "blank", "empty")
MIN_FORMAL_IMAGE_WIDTH = 64
MIN_FORMAL_IMAGE_HEIGHT = 64


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_result(path: pathlib.Path, project_dir: pathlib.Path, requested_role: str, media_type: str) -> dict[str, Any]:
    try:
        resolved = pathlib.Path(path).resolve()
    except OSError:
        resolved = pathlib.Path(path)
    try:
        relative = resolved.relative_to(project_dir.resolve()).as_posix()
    except ValueError:
        relative = ""
    placeholder = any(token in resolved.name.lower() for token in PLACEHOLDER_TOKENS)
    return {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "media_type": media_type,
        "requested_role": requested_role,
        "path": str(resolved),
        "relative_path": relative,
        "suffix": resolved.suffix.lower(),
        "detected_format": "",
        "sha256": canonical_evidence_hash.sha256_file(resolved) if resolved.is_file() else "",
        "size_bytes": resolved.stat().st_size if resolved.is_file() else 0,
        "status": EvidenceStatus.FAIL.value,
        "failure_reason": "",
        "decoder": "",
        "decoder_version": "",
        "width": 0,
        "height": 0,
        "duration_seconds": 0.0,
        "codec_name": "",
        "stream_count": 0,
        "decoded_frame_count": 0,
        "blank_or_solid": False,
        "placeholder_name": placeholder,
        "validated_at": _now(),
    }


def _fail(result: dict[str, Any], reason: str, status: EvidenceStatus = EvidenceStatus.FAIL) -> dict[str, Any]:
    result["status"] = status.value
    result["failure_reason"] = reason
    return result


def _within_project(path: pathlib.Path, project: pathlib.Path) -> bool:
    try:
        resolved = path.resolve()
        root = project.resolve()
        return resolved == root or root in resolved.parents
    except OSError:
        return False


def _image_codec_to_format(codec_name: str, suffix: str) -> str:
    codec = codec_name.lower()
    if codec in {"mjpeg", "jpeg"}:
        return "JPEG"
    if codec == "png":
        return "PNG"
    if codec == "webp":
        return "WEBP"
    if suffix in IMAGE_SUFFIXES:
        return IMAGE_SUFFIXES[suffix]
    return codec_name.upper()


def _blank_or_solid_rgb(raw: bytes, width: int, height: int) -> bool:
    if width <= 0 or height <= 0 or len(raw) < width * height * 3:
        return True
    step_x = max(1, width // 64)
    step_y = max(1, height // 64)
    colors: set[tuple[int, int, int]] = set()
    min_rgb = [255, 255, 255]
    max_rgb = [0, 0, 0]
    for y in range(0, height, step_y):
        for x in range(0, width, step_x):
            idx = (y * width + x) * 3
            rgb = tuple(raw[idx : idx + 3])
            if len(rgb) != 3:
                continue
            colors.add(rgb)
            for channel, value in enumerate(rgb):
                min_rgb[channel] = min(min_rgb[channel], value)
                max_rgb[channel] = max(max_rgb[channel], value)
    varied_channels = sum(1 for low, high in zip(min_rgb, max_rgb) if high - low > 8)
    return varied_channels < 2 or len(colors) < 16


def _validate_image_with_ffmpeg(result: dict[str, Any], resolved: pathlib.Path, requested_role: str) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not ffprobe or not ffmpeg:
        result["decoder"] = "ffprobe/ffmpeg"
        return _fail(result, "decoder_unavailable", EvidenceStatus.BLOCKED_ENVIRONMENT)
    result["decoder"] = "ffprobe+ffmpeg"
    result["decoder_version"] = f"{_tool_version(ffprobe)} | {_tool_version(ffmpeg)}"
    probe_cmd = [ffprobe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(resolved)]
    try:
        probe = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return _fail(result, "ffprobe_timeout")
    if probe.returncode != 0:
        return _fail(result, "image_decode_failed:ffprobe_nonzero")
    try:
        metadata = json.loads(probe.stdout or "{}")
    except json.JSONDecodeError:
        return _fail(result, "image_decode_failed:ffprobe_invalid_json")
    streams = metadata.get("streams", []) if isinstance(metadata.get("streams"), list) else []
    image_streams = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"]
    if not image_streams:
        return _fail(result, "image_decode_failed:no_image_stream")
    stream = image_streams[0]
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    detected = _image_codec_to_format(str(stream.get("codec_name") or ""), str(result["suffix"]))
    decode_cmd = [ffmpeg, "-v", "error", "-i", str(resolved), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    try:
        decode = subprocess.run(decode_cmd, capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        return _fail(result, "image_decode_failed:ffmpeg_timeout")
    if decode.returncode != 0:
        return _fail(result, "image_decode_failed:ffmpeg_nonzero")
    blank_or_solid = _blank_or_solid_rgb(decode.stdout or b"", width, height)
    result.update(
        {
            "detected_format": detected,
            "width": width,
            "height": height,
            "blank_or_solid": bool(blank_or_solid),
            "decoded_frame_count": 1,
        }
    )
    expected = IMAGE_SUFFIXES[result["suffix"]]
    if detected != expected:
        return _fail(result, "format_suffix_mismatch")
    if width <= 0 or height <= 0:
        return _fail(result, "invalid_dimensions")
    if requested_role in {"background", "sprite", "generated_image"}:
        if width < MIN_FORMAL_IMAGE_WIDTH or height < MIN_FORMAL_IMAGE_HEIGHT:
            return _fail(result, "too_small")
        if blank_or_solid:
            return _fail(result, "blank_or_solid")
    result["status"] = EvidenceStatus.PASS.value
    result["failure_reason"] = ""
    return result


def validate_image(path: str | pathlib.Path, project_dir: str | pathlib.Path, *, requested_role: str) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    target = pathlib.Path(path)
    result = _base_result(target, project, requested_role, "image")
    resolved = pathlib.Path(result["path"])
    if not resolved.exists():
        return _fail(result, "missing")
    if not resolved.is_file():
        return _fail(result, "not_file")
    if not _within_project(resolved, project):
        return _fail(result, "outside_project")
    if result["suffix"] not in IMAGE_SUFFIXES:
        return _fail(result, "unsupported_suffix")
    if result["placeholder_name"]:
        return _fail(result, "placeholder_name")
    if result["size_bytes"] <= 0:
        return _fail(result, "empty_file")
    try:
        from PIL import Image, ImageChops
        import PIL
    except Exception:
        return _validate_image_with_ffmpeg(result, resolved, requested_role)
    result["decoder"] = "Pillow"
    result["decoder_version"] = str(getattr(PIL, "__version__", "unknown"))
    try:
        with Image.open(resolved) as img:
            detected = str(img.format or "").upper()
            img.verify()
        with Image.open(resolved) as img:
            detected = str(img.format or detected).upper()
            rgba = img.convert("RGBA")
            rgba.load()
            width, height = rgba.size
            alpha = rgba.getchannel("A")
            fully_transparent = alpha.getbbox() is None
            sample = rgba.resize((min(64, width), min(64, height)))
            colors = sample.getcolors(maxcolors=4096) or []
            rgb = sample.convert("RGB")
            extrema = rgb.getextrema()
            varied_channels = sum(1 for low, high in extrema if high - low > 8)
            solid = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
            bbox = ImageChops.difference(rgb, solid).getbbox()
            blank_or_solid = fully_transparent or bbox is None or varied_channels < 2 or len(colors) < 16
    except Exception as exc:
        return _fail(result, f"image_decode_failed:{exc}")
    result.update(
        {
            "detected_format": detected,
            "width": int(width),
            "height": int(height),
            "blank_or_solid": bool(blank_or_solid),
            "decoded_frame_count": 1,
        }
    )
    expected = IMAGE_SUFFIXES[result["suffix"]]
    if detected != expected:
        return _fail(result, "format_suffix_mismatch")
    if width <= 0 or height <= 0:
        return _fail(result, "invalid_dimensions")
    if requested_role in {"background", "sprite", "generated_image"}:
        if width < MIN_FORMAL_IMAGE_WIDTH or height < MIN_FORMAL_IMAGE_HEIGHT:
            return _fail(result, "too_small")
        if blank_or_solid:
            return _fail(result, "blank_or_solid")
    result["status"] = EvidenceStatus.PASS.value
    result["failure_reason"] = ""
    return result


def _tool_version(executable: str) -> str:
    try:
        proc = subprocess.run([executable, "-version"], capture_output=True, text=True, timeout=5)
    except Exception:
        return "unknown"
    return (proc.stdout or proc.stderr or "unknown").splitlines()[0].strip()


def validate_video(path: str | pathlib.Path, project_dir: str | pathlib.Path, *, requested_role: str, timeout: float = 10.0) -> dict[str, Any]:
    project = pathlib.Path(project_dir).resolve()
    target = pathlib.Path(path)
    result = _base_result(target, project, requested_role, "video")
    resolved = pathlib.Path(result["path"])
    if not resolved.exists():
        return _fail(result, "missing")
    if not resolved.is_file():
        return _fail(result, "not_file")
    if not _within_project(resolved, project):
        return _fail(result, "outside_project")
    if result["suffix"] not in VIDEO_SUFFIXES:
        return _fail(result, "unsupported_suffix")
    if result["placeholder_name"]:
        return _fail(result, "placeholder_name")
    if result["size_bytes"] <= 0:
        return _fail(result, "empty_file")
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not ffprobe or not ffmpeg:
        result["decoder"] = "ffprobe/ffmpeg"
        return _fail(result, "decoder_unavailable", EvidenceStatus.BLOCKED_ENVIRONMENT)
    result["decoder"] = "ffprobe+ffmpeg"
    result["decoder_version"] = f"{_tool_version(ffprobe)} | {_tool_version(ffmpeg)}"
    probe_cmd = [ffprobe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(resolved)]
    try:
        probe = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return _fail(result, "ffprobe_timeout")
    except Exception as exc:
        return _fail(result, f"ffprobe_failed:{exc}")
    if probe.returncode != 0:
        return _fail(result, "ffprobe_nonzero")
    try:
        metadata = json.loads(probe.stdout or "{}")
    except json.JSONDecodeError:
        return _fail(result, "ffprobe_invalid_json")
    streams = metadata.get("streams", []) if isinstance(metadata.get("streams"), list) else []
    video_streams = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"]
    result["stream_count"] = len(video_streams)
    if not video_streams:
        return _fail(result, "no_video_stream")
    stream = video_streams[0]
    fmt = metadata.get("format", {}) if isinstance(metadata.get("format"), dict) else {}
    duration = float(stream.get("duration") or fmt.get("duration") or 0.0)
    result.update(
        {
            "detected_format": str(fmt.get("format_name") or ""),
            "width": int(stream.get("width") or 0),
            "height": int(stream.get("height") or 0),
            "duration_seconds": duration,
            "codec_name": str(stream.get("codec_name") or ""),
        }
    )
    if result["width"] <= 0 or result["height"] <= 0:
        return _fail(result, "invalid_dimensions")
    if result["duration_seconds"] <= 0:
        return _fail(result, "invalid_duration")
    if not result["codec_name"]:
        return _fail(result, "missing_codec")
    decode_cmd = [ffmpeg, "-v", "error", "-i", str(resolved), "-map", "0:v:0", "-frames:v", "1", "-f", "null", "-"]
    try:
        decode = subprocess.run(decode_cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return _fail(result, "ffmpeg_timeout")
    except Exception as exc:
        return _fail(result, f"ffmpeg_failed:{exc}")
    if decode.returncode != 0:
        return _fail(result, "ffmpeg_decode_nonzero")
    result["decoded_frame_count"] = 1
    result["status"] = EvidenceStatus.PASS.value
    result["failure_reason"] = ""
    return result


def validate_media(path: str | pathlib.Path, project_dir: str | pathlib.Path, *, requested_role: str) -> dict[str, Any]:
    suffix = pathlib.Path(path).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return validate_image(path, project_dir, requested_role=requested_role)
    if suffix in VIDEO_SUFFIXES:
        return validate_video(path, project_dir, requested_role=requested_role)
    project = pathlib.Path(project_dir).resolve()
    result = _base_result(pathlib.Path(path), project, requested_role, "unknown")
    return _fail(result, "unsupported_suffix")
