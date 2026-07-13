from __future__ import annotations

import hashlib
import json
import pathlib
import struct
import zlib
from typing import Any

try:
    from PIL import Image, ImageStat
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageStat = None  # type: ignore


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def average_hash(path: pathlib.Path) -> str:
    if Image is None:
        return _png_average_hash(path)
    with Image.open(path) as image:
        small = image.convert("L").resize((8, 8))
        pixels = list(small.getdata())
    avg = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= avg else "0" for pixel in pixels)
    return f"{int(bits, 2):016x}"


def _paeth(left: int, up: int, up_left: int) -> int:
    p = left + up - up_left
    pa = abs(p - left)
    pb = abs(p - up)
    pc = abs(p - up_left)
    if pa <= pb and pa <= pc:
        return left
    if pb <= pc:
        return up
    return up_left


def _decode_png_pixels(path: pathlib.Path) -> tuple[int, int, list[tuple[int, int, int]]]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a png")
    pos = 8
    width = height = bit_depth = color_type = 0
    idat = bytearray()
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _compression, _filter, _interlace = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"IDAT":
            idat.extend(chunk)
        elif kind == b"IEND":
            break
    if not width or not height or bit_depth != 8 or color_type not in {0, 2, 4, 6}:
        raise ValueError("unsupported png format")
    channels = {0: 1, 2: 3, 4: 2, 6: 4}[color_type]
    stride = width * channels
    raw = zlib.decompress(bytes(idat))
    pixels: list[tuple[int, int, int]] = []
    previous = bytearray(stride)
    offset = 0
    for _row in range(height):
        filter_type = raw[offset]
        offset += 1
        row = bytearray(raw[offset : offset + stride])
        offset += stride
        for idx, value in enumerate(row):
            left = row[idx - channels] if idx >= channels else 0
            up = previous[idx]
            up_left = previous[idx - channels] if idx >= channels else 0
            if filter_type == 1:
                row[idx] = (value + left) & 0xFF
            elif filter_type == 2:
                row[idx] = (value + up) & 0xFF
            elif filter_type == 3:
                row[idx] = (value + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                row[idx] = (value + _paeth(left, up, up_left)) & 0xFF
            elif filter_type != 0:
                raise ValueError("unsupported png filter")
        previous = row
        for col in range(width):
            start = col * channels
            if color_type == 0:
                gray = row[start]
                pixels.append((gray, gray, gray))
            elif color_type == 4:
                gray = row[start]
                pixels.append((gray, gray, gray))
            else:
                pixels.append((row[start], row[start + 1], row[start + 2]))
    return width, height, pixels


def _png_average_hash(path: pathlib.Path) -> str:
    try:
        width, height, pixels = _decode_png_pixels(path)
    except Exception:
        return ""
    cells = [0.0] * 64
    counts = [0] * 64
    for y in range(height):
        cy = min(7, y * 8 // height)
        row_offset = y * width
        for x in range(width):
            cx = min(7, x * 8 // width)
            r, g, b = pixels[row_offset + x]
            cells[cy * 8 + cx] += 0.299 * r + 0.587 * g + 0.114 * b
            counts[cy * 8 + cx] += 1
    values = [cells[idx] / max(1, counts[idx]) for idx in range(64)]
    avg = sum(values) / len(values)
    bits = "".join("1" if value >= avg else "0" for value in values)
    return f"{int(bits, 2):016x}"


def _inspect_png_stdlib(target: pathlib.Path) -> dict[str, Any]:
    try:
        width, height, pixels = _decode_png_pixels(target)
    except Exception as exc:
        return {"status": "NEEDS_REWORK", "reason": "decode_failed", "path": str(target), "error": str(exc)}
    reasons: list[str] = []
    if width < 800 or height < 600:
        reasons.append("too_small")
    count = max(1, len(pixels))
    luminance_sum = 0.0
    luminance_square_sum = 0.0
    mins = [255, 255, 255]
    maxes = [0, 0, 0]
    for r, g, b in pixels:
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        luminance_sum += lum
        luminance_square_sum += lum * lum
        mins[0] = min(mins[0], r)
        mins[1] = min(mins[1], g)
        mins[2] = min(mins[2], b)
        maxes[0] = max(maxes[0], r)
        maxes[1] = max(maxes[1], g)
        maxes[2] = max(maxes[2], b)
    mean = luminance_sum / count
    variance = max(0.0, (luminance_square_sum / count) - (mean * mean))
    if variance <= 1.0:
        reasons.append("low_variance_or_blank")
    if mins == maxes:
        reasons.append("pure_color")
    return {
        "status": "PASS" if not reasons else "NEEDS_REWORK",
        "path": str(target),
        "width": width,
        "height": height,
        "variance": variance,
        "sha256": sha256_file(target),
        "perceptual_hash": _png_average_hash(target),
        "reasons": reasons,
    }


def inspect_screenshot(path: str | pathlib.Path) -> dict[str, Any]:
    target = pathlib.Path(path)
    if not target.exists() or not target.is_file():
        return {"status": "NEEDS_REWORK", "reason": "missing", "path": str(target)}
    if Image is None:
        return _inspect_png_stdlib(target)
    try:
        with Image.open(target) as image:
            image.verify()
        with Image.open(target) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            stat = ImageStat.Stat(rgb)
            variance = sum(stat.var) / max(1, len(stat.var))
            extrema = rgb.getextrema()
    except Exception as exc:
        return {"status": "NEEDS_REWORK", "reason": "decode_failed", "path": str(target), "error": str(exc)}
    reasons: list[str] = []
    if width < 800 or height < 600:
        reasons.append("too_small")
    if variance <= 1.0:
        reasons.append("low_variance_or_blank")
    if all(channel[0] == channel[1] for channel in extrema):
        reasons.append("pure_color")
    return {
        "status": "PASS" if not reasons else "NEEDS_REWORK",
        "path": str(target),
        "width": width,
        "height": height,
        "variance": variance,
        "sha256": sha256_file(target),
        "perceptual_hash": average_hash(target),
        "reasons": reasons,
    }


def screenshot_integrity_gate(screenshots: list[dict[str, Any]], *, candidate_id: str, database_hash: str, browser_session_id: str = "") -> dict[str, Any]:
    inspections: list[dict[str, Any]] = []
    bad: list[dict[str, Any]] = []
    seen_sha: set[str] = set()
    seen_phash: set[str] = set()
    duplicates = 0
    for screenshot in screenshots:
        inspection = inspect_screenshot(str(screenshot.get("path", "")))
        inspection["candidate_id"] = screenshot.get("candidate_id", "")
        inspection["database_hash"] = screenshot.get("database_hash", "")
        inspection["browser_session_id"] = screenshot.get("browser_session_id", "")
        inspection["url"] = screenshot.get("url", "")
        inspection["action_id"] = screenshot.get("action_id", "")
        inspection["captured_after_action"] = bool(screenshot.get("captured_after_action", False))
        reasons = list(inspection.get("reasons", []))
        if inspection.get("candidate_id") != candidate_id:
            reasons.append("wrong_candidate")
        if database_hash and inspection.get("database_hash") != database_hash:
            reasons.append("wrong_database")
        if browser_session_id and inspection.get("browser_session_id") != browser_session_id:
            reasons.append("wrong_browser_session")
        if not inspection.get("captured_after_action"):
            reasons.append("not_after_user_action")
        sha = str(inspection.get("sha256", ""))
        phash = str(inspection.get("perceptual_hash", ""))
        if sha and sha in seen_sha:
            reasons.append("duplicate_sha")
            duplicates += 1
        if phash and phash in seen_phash:
            reasons.append("duplicate_perceptual_hash")
            duplicates += 1
        if sha:
            seen_sha.add(sha)
        if phash:
            seen_phash.add(phash)
        inspection["reasons"] = reasons
        inspection["status"] = "PASS" if not reasons and inspection.get("status") == "PASS" else "NEEDS_REWORK"
        inspections.append(inspection)
        if inspection["status"] != "PASS":
            bad.append(inspection)
    return {
        "status": "PASS" if screenshots and not bad else "NEEDS_REWORK",
        "valid_count": len([item for item in inspections if item.get("status") == "PASS"]),
        "bad_count": len(bad),
        "duplicate_count": duplicates,
        "inspections": inspections,
    }


def write_gate(path: str | pathlib.Path, gate: dict[str, Any]) -> None:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
