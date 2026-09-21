from __future__ import annotations

import pathlib
import struct
import subprocess
import sys
import zlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import canonical_media_validation as media


def _write_varied_image(path: pathlib.Path, fmt: str = "PNG", size: tuple[int, int] = (96, 80)) -> None:
    width, height = size
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={width}x{height}:rate=1",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _write_rgba_png(path: pathlib.Path, width: int, height: int, rgba: tuple[int, int, int, int]) -> None:
    rows = []
    for _y in range(height):
        row = bytearray([0])
        for _x in range(width):
            row.extend(rgba)
        rows.append(bytes(row))
    data = b"\x89PNG\r\n\x1a\n"
    data += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    data += _png_chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
    data += _png_chunk(b"IEND", b"")
    path.write_bytes(data)


def _make_video(path: pathlib.Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=96x64:rate=10:duration=0.6",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_valid_png_jpeg_and_webp_pass(tmp_path: pathlib.Path) -> None:
    cases = [("background.png", "PNG", "background"), ("sprite.jpg", "JPEG", "sprite"), ("generated.webp", "WEBP", "generated_image")]
    for name, fmt, role in cases:
        path = tmp_path / name
        _write_varied_image(path, fmt)
        result = media.validate_media(path, tmp_path, requested_role=role)
        assert result["status"] == "PASS", result
        assert result["sha256"].startswith("sha256:")
        assert result["width"] > 0
        assert result["height"] > 0
        assert result["detected_format"] == ("JPEG" if fmt == "JPEG" else fmt)


def test_invalid_images_fail(tmp_path: pathlib.Path) -> None:
    (tmp_path / "fake.png").write_bytes(b"png")
    (tmp_path / "background.png").write_bytes(b"real-background")
    (tmp_path / "renamed.jpg").write_text("hello", encoding="utf-8")
    (tmp_path / "signature.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    truncated = tmp_path / "truncated.png"
    _write_varied_image(truncated, "PNG")
    truncated.write_bytes(truncated.read_bytes()[:24])
    for name in ("fake.png", "background.png", "renamed.jpg", "signature.png", "truncated.png"):
        result = media.validate_media(tmp_path / name, tmp_path, requested_role="background")
        assert result["status"] == "FAIL", (name, result)


def test_blank_transparent_placeholder_and_outside_images_fail(tmp_path: pathlib.Path) -> None:
    _write_rgba_png(tmp_path / "tiny.png", 1, 1, (1, 1, 1, 255))
    _write_rgba_png(tmp_path / "transparent.png", 96, 96, (0, 0, 0, 0))
    _write_varied_image(tmp_path / "fallback_mock_background.png", "PNG")
    outside = tmp_path.parent / "outside_background.png"
    _write_varied_image(outside, "PNG")
    for path in (tmp_path / "tiny.png", tmp_path / "transparent.png", tmp_path / "fallback_mock_background.png", outside):
        result = media.validate_media(path, tmp_path, requested_role="background")
        assert result["status"] == "FAIL", result


def test_valid_mp4_passes_bounded_decode(tmp_path: pathlib.Path) -> None:
    video = tmp_path / "workflow_demo.mp4"
    _make_video(video)
    result = media.validate_media(video, tmp_path, requested_role="video")
    assert result["status"] == "PASS", result
    assert result["stream_count"] >= 1
    assert result["duration_seconds"] > 0
    assert result["width"] > 0
    assert result["height"] > 0
    assert result["decoded_frame_count"] == 1
    assert result["sha256"].startswith("sha256:")


def test_invalid_videos_fail(tmp_path: pathlib.Path) -> None:
    (tmp_path / "demo.mp4").write_bytes(b"real-video")
    (tmp_path / "renamed.webm").write_text("hello", encoding="utf-8")
    (tmp_path / "zero.mp4").write_bytes(b"")
    truncated = tmp_path / "truncated.mp4"
    _make_video(truncated)
    truncated.write_bytes(truncated.read_bytes()[:32])
    for name in ("demo.mp4", "renamed.webm", "zero.mp4", "truncated.mp4"):
        result = media.validate_media(tmp_path / name, tmp_path, requested_role="video")
        assert result["status"] == "FAIL", (name, result)


def test_audio_only_container_fails_no_video_stream(tmp_path: pathlib.Path) -> None:
    audio_only = tmp_path / "audio_only.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=1000:duration=0.5", "-vn", str(audio_only)],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    result = media.validate_media(audio_only, tmp_path, requested_role="video")
    assert result["status"] == "FAIL"
    assert result["failure_reason"] == "no_video_stream"


def test_video_decoder_unavailable_is_blocked_environment(tmp_path: pathlib.Path, monkeypatch) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"not used")
    monkeypatch.setattr(media.shutil, "which", lambda _name: None)
    result = media.validate_media(video, tmp_path, requested_role="video")
    assert result["status"] == "BLOCKED_ENVIRONMENT"
    assert result["failure_reason"] == "decoder_unavailable"


def test_ffprobe_and_ffmpeg_failures_do_not_pass(tmp_path: pathlib.Path, monkeypatch) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"not a real video")
    monkeypatch.setattr(media.shutil, "which", lambda name: f"fake-{name}")

    def fake_probe_nonzero(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, "", "probe failed")

    monkeypatch.setattr(media.subprocess, "run", fake_probe_nonzero)
    assert media.validate_media(video, tmp_path, requested_role="video")["failure_reason"] == "ffprobe_nonzero"

    def fake_decode_nonzero(command, **_kwargs):
        if "ffprobe" in str(command[0]):
            return subprocess.CompletedProcess(
                command,
                0,
                '{"format":{"format_name":"mov,mp4,m4a,3gp,3g2,mj2","duration":"0.5"},"streams":[{"codec_type":"video","codec_name":"h264","width":96,"height":64}]}',
                "",
            )
        return subprocess.CompletedProcess(command, 1, "", "decode failed")

    monkeypatch.setattr(media.subprocess, "run", fake_decode_nonzero)
    assert media.validate_media(video, tmp_path, requested_role="video")["failure_reason"] == "ffmpeg_decode_nonzero"

    def fake_timeout(command, **_kwargs):
        if "ffprobe" in str(command[0]):
            return fake_decode_nonzero(command)
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(media.subprocess, "run", fake_timeout)
    assert media.validate_media(video, tmp_path, requested_role="video")["failure_reason"] == "ffmpeg_timeout"
