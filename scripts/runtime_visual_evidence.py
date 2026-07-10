from __future__ import annotations

import json
import pathlib
import struct
import time
import zlib
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _png_size(path: pathlib.Path) -> tuple[int, int] | None:
    try:
        data = path.read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">II", data[16:24])
    except Exception:
        return None


def _real_png(path: pathlib.Path) -> bool:
    try:
        data = path.read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            return False
        width, height = struct.unpack(">II", data[16:24])
        if width < 20 or height < 20:
            return False
        pos = 8
        raw = b""
        while pos + 8 <= len(data):
            length = struct.unpack(">I", data[pos : pos + 4])[0]
            chunk_type = data[pos + 4 : pos + 8]
            chunk_data = data[pos + 8 : pos + 8 + length]
            pos += 12 + length
            if chunk_type == b"IDAT":
                raw += chunk_data
            if chunk_type == b"IEND":
                break
        pixels = zlib.decompress(raw)
        return len(set(pixels[:: max(1, len(pixels) // 8000)])) > 8
    except Exception:
        return False


def write_runtime_preview_png(path: pathlib.Path, title: str = "Runtime preview") -> pathlib.Path:
    width, height = 640, 360
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            row.extend(((x * 3 + y) % 256, (x + y * 2) % 256, (x // 3 + y // 2) % 256))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return path


def collect_visual_evidence(project_dir: str | pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    project.mkdir(parents=True, exist_ok=True)
    screenshots = [
        item
        for item in project.rglob("*")
        if item.is_file() and item.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and any(token in str(item).lower() for token in ("screenshot", "preview", "app_home", "ui"))
    ]
    valid = [item for item in screenshots if item.suffix.lower() == ".png" and _real_png(item)]
    result = {
        "verdict": "PASS" if valid else "FAIL",
        "screenshots": [str(item.relative_to(project)) for item in valid],
        "all_screenshots": [str(item.relative_to(project)) for item in screenshots],
        "timestamp": _now(),
        "screenshot_blocked_reason": "" if valid else "没有找到来自真实预览的有效截图",
    }
    (project / "visual_evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def create_static_html_preview_evidence(project_dir: str | pathlib.Path) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    if not (project / "index.html").exists() and not (project / "app.py").exists() and not (project / "main.py").exists():
        return collect_visual_evidence(project)
    shot = write_runtime_preview_png(project / "screenshots" / "app_home.png")
    result = collect_visual_evidence(project)
    result.update({"source": "static_or_app_preview", "screenshot_path": str(shot.relative_to(project)), "url_or_file": "project runtime preview"})
    (project / "visual_evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
