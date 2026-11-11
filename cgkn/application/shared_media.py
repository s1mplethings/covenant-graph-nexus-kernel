"""Shared deterministic media implementations registered in the capability registry.

These functions do not depend on a project tree, goal, acceptance or budget.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys

TRIAL = pathlib.Path(r"C:\Users\sunom\VeriArbor-Experiments\real-product-growth-v1-20261108")
ACCEPTANCE_TOOL = TRIAL / "tools" / "media_acceptance.py"
FFPROBE = r"C:\Program Files\ffmpeg\bin\ffprobe.exe"


def sha256(path: pathlib.Path | str) -> str:
    h = hashlib.sha256()
    with pathlib.Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(path: pathlib.Path | str) -> dict:
    proc = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration,size",
                           "-show_entries", "stream=codec_type,codec_name,width,height,sample_rate,channels",
                           "-of", "json", str(path)],
                          capture_output=True, text=True, timeout=120, check=False)
    if proc.returncode:
        raise RuntimeError("ffprobe failed: " + proc.stderr[-500:])
    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    return {"duration_ms": round(float(data.get("format", {}).get("duration") or 0) * 1000),
            "size": int(data.get("format", {}).get("size") or 0),
            "width": int(video.get("width")) if video else None,
            "height": int(video.get("height")) if video else None,
            "has_audio": audio is not None}


def technical_acceptance(path: pathlib.Path | str, out: pathlib.Path | str,
                         *, require_audio: bool = True, min_seconds: float = 1.0) -> dict:
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(ACCEPTANCE_TOOL), str(path), "--min-seconds", str(min_seconds),
           "--out", str(out)]
    if require_audio:
        cmd.append("--require-audio")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
    receipt = json.loads(out.read_text(encoding="utf-8")) if out.is_file() else {}
    receipt["tool_returncode"] = proc.returncode
    return receipt


__all__ = ["sha256", "probe", "technical_acceptance"]
