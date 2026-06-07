#!/usr/bin/env python3
from __future__ import annotations

import os
import pathlib
import urllib.error
import urllib.request
from typing import Any


IMAGE_TERMS = (
    "图片",
    "图像",
    "生成图",
    "背景",
    "背景图",
    "立绘",
    "角色图",
    "character",
    "sprite",
    "background",
    "image",
    "text-to-image",
)
STRICT_TERMS = (
    "本地图片模型",
    "本地的图片模型",
    "本地生成",
    "本地生图",
    "本地图片生成",
    "本地立绘生成",
    "本地背景生成",
    "真实",
    "正经",
    "直接生成",
    "stable diffusion",
    "comfyui",
    "automatic1111",
    "a1111",
    "sd_model_dir",
    "diffusers",
    "flux",
    "sdxl",
)
MODEL_EXTENSIONS = {".safetensors", ".ckpt", ".pt", ".pth", ".bin"}
MODEL_HINT_FILES = {"model_index.json", "unet", "vae", "text_encoder", "scheduler"}
IMAGE_MODEL_NAME_HINTS = (
    "stable-diffusion",
    "sdxl",
    "sd-1",
    "sd-2",
    "flux",
    "diffusion",
    "dreamshaper",
    "anything-v",
    "juggernaut",
    "realvis",
    "counterfeit",
    "animagine",
    "deliberate",
    "majicmix",
    "revanimated",
)


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(term.lower() in lowered for term in terms)


def requests_local_image_model(text: str) -> bool:
    value = str(text or "").lower()
    explicit_local_model = _contains_any(
        value,
        (
            "本地图片模型",
            "本地的图片模型",
            "本地生图",
            "本地图片生成",
            "本地立绘生成",
            "本地背景生成",
            "stable diffusion",
            "comfyui",
            "automatic1111",
            "a1111",
            "sd_model_dir",
            "diffusers",
            "flux",
            "sdxl",
        ),
    )
    if explicit_local_model and _contains_any(value, IMAGE_TERMS):
        return True
    return False


def _get_json(url: str, timeout: float) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=max(0.2, float(timeout))) as response:
            if 200 <= int(getattr(response, "status", 0) or 0) < 300:
                return True, ""
            return False, f"http {getattr(response, 'status', '')}"
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return False, str(exc)[:180]


def _looks_like_image_model_path(path: pathlib.Path) -> bool:
    lowered = str(path).lower().replace("\\", "/")
    return any(hint in lowered for hint in IMAGE_MODEL_NAME_HINTS)


def _is_huggingface_hub(path: pathlib.Path) -> bool:
    lowered = str(path).lower().replace("\\", "/")
    return "/.cache/huggingface/hub" in lowered or lowered.endswith("/huggingface/hub")


def _has_model_file(path: pathlib.Path, *, min_bytes: int = 1024 * 1024) -> bool:
    if not path.exists():
        return False
    if path.is_file():
        return path.suffix.lower() in MODEL_EXTENSIONS and path.stat().st_size >= min_bytes
    hf_hub = _is_huggingface_hub(path)
    scanned = 0
    try:
        for child in path.rglob("*"):
            scanned += 1
            if scanned > 5000:
                break
            if ".no_exist" in {part.lower() for part in child.parts}:
                continue
            if not child.is_file():
                continue
            name = child.name.lower()
            if child.suffix.lower() in MODEL_EXTENSIONS and child.stat().st_size >= min_bytes and (not hf_hub or _looks_like_image_model_path(child)):
                return True
            if name in MODEL_HINT_FILES and _looks_like_image_model_path(child):
                return True
    except OSError:
        return False
    return False


def _common_model_dirs(project_root: pathlib.Path | None) -> list[pathlib.Path]:
    userprofile = pathlib.Path(os.environ.get("USERPROFILE") or pathlib.Path.home())
    roots: list[pathlib.Path] = []
    if project_root:
        roots.extend([project_root / "models", project_root / "generated" / "models"])
    roots.extend(
        [
            pathlib.Path("D:/CGKN/models"),
            pathlib.Path("D:/models"),
            pathlib.Path("D:/AI/models"),
            pathlib.Path("D:/ComfyUI/models/checkpoints"),
            pathlib.Path("D:/stable-diffusion-webui/models/Stable-diffusion"),
            userprofile / "ComfyUI" / "models" / "checkpoints",
            userprofile / "stable-diffusion-webui" / "models" / "Stable-diffusion",
            userprofile / ".cache" / "huggingface" / "hub",
        ]
    )
    out: list[pathlib.Path] = []
    seen: set[str] = set()
    for path in roots:
        key = str(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def discover_local_image_backends(project_root: str | pathlib.Path | None = None, *, timeout: float = 0.8) -> dict[str, Any]:
    root = pathlib.Path(project_root) if project_root else None
    checked: list[dict[str, str]] = []
    backends: list[dict[str, str]] = []

    comfy_urls = [
        os.environ.get("CGNK_COMFYUI_URL", "").strip(),
        os.environ.get("COMFYUI_URL", "").strip(),
        "http://127.0.0.1:8188",
    ]
    a1111_urls = [
        os.environ.get("CGNK_A1111_URL", "").strip(),
        os.environ.get("A1111_URL", "").strip(),
        "http://127.0.0.1:7860",
    ]
    for url in [item.rstrip("/") for item in comfy_urls if item.strip()]:
        ok, error = _get_json(url + "/system_stats", timeout)
        checked.append({"kind": "ComfyUI", "target": url, "status": "available" if ok else "missing", "error": error})
        if ok:
            backends.append({"kind": "ComfyUI", "target": url})
            break
    for url in [item.rstrip("/") for item in a1111_urls if item.strip()]:
        ok, error = _get_json(url + "/sdapi/v1/sd-models", timeout)
        checked.append({"kind": "AUTOMATIC1111", "target": url, "status": "available" if ok else "missing", "error": error})
        if ok:
            backends.append({"kind": "AUTOMATIC1111", "target": url})
            break

    model_envs = [os.environ.get("CGNK_SD_MODEL_DIR", ""), os.environ.get("SD_MODEL_DIR", "")]
    for value in [item for item in model_envs if str(item).strip()]:
        path = pathlib.Path(str(value).strip())
        ok = _has_model_file(path)
        checked.append({"kind": "SD_MODEL_DIR", "target": str(path), "status": "available" if ok else "missing", "error": ""})
        if ok:
            backends.append({"kind": "SD_MODEL_DIR", "target": str(path)})

    for path in _common_model_dirs(root):
        ok = _has_model_file(path)
        checked.append({"kind": "model_dir", "target": str(path), "status": "available" if ok else "missing", "error": ""})
        if ok:
            backends.append({"kind": "model_dir", "target": str(path)})
            break

    available = bool(backends)
    questions = []
    if not available:
        questions = [
            "本地图片生成准备用哪个后端：ComfyUI、AUTOMATIC1111，还是直接给 SD_MODEL_DIR/模型目录？",
            "背景和立绘是否使用同一个本地模型？如果不同，请分别给服务地址或模型路径。",
        ]
    return {
        "available": available,
        "backends": backends,
        "checked": checked[:40],
        "missing_reason": "" if available else "未发现可调用的 ComfyUI/AUTOMATIC1111 服务，也未发现可用的 Stable Diffusion/FLUX 模型目录。",
        "recommended_questions": questions,
    }


def critical_questions_for_text(text: str, project_root: str | pathlib.Path | None = None) -> tuple[list[str], dict[str, Any]]:
    if not requests_local_image_model(text):
        return [], {"available": False, "backends": [], "checked": [], "missing_reason": "", "recommended_questions": []}
    discovery = discover_local_image_backends(project_root)
    if discovery.get("available"):
        return [], discovery
    return list(discovery.get("recommended_questions", []))[:2], discovery
