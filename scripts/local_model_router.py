#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import urllib.error
import urllib.request
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_LOCAL_TASKS = {
    "customer_public_reply",
    "customer_status",
}

LOCAL_GENERATION_TASKS = {
    "customer_classification",
    "backend_dialogue",
    "pipeline_planner",
    "cfo_pipeline",
    "context_support",
    "risk_support",
    "foundation",
    "qa",
}

PUBLIC_REPLY_TASKS = {
    "customer_public_reply",
    "customer_status",
}


def env_truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def local_model_requested() -> bool:
    return (
        env_truthy("CGNK_USE_LOCAL_MODEL")
        or bool(str(os.environ.get("CGNK_LOCAL_MODEL_CMD", "")).strip())
        or bool(str(os.environ.get("CGNK_LOCAL_MODEL_TASKS", "")).strip())
    )


def enabled_tasks() -> set[str]:
    raw = str(os.environ.get("CGNK_LOCAL_MODEL_TASKS", "")).strip()
    if not raw:
        return set(DEFAULT_LOCAL_TASKS)
    values = {item.strip().lower() for item in re.split(r"[,;\s]+", raw) if item.strip()}
    return values or set(DEFAULT_LOCAL_TASKS)


def task_enabled(task: str) -> bool:
    if not local_model_requested():
        return False
    tasks = enabled_tasks()
    return "all" in tasks or str(task or "").strip().lower() in tasks


def task_affects_generation(task: str) -> bool:
    return str(task or "").strip().lower() in LOCAL_GENERATION_TASKS


def task_is_public_reply_only(task: str) -> bool:
    return str(task or "").strip().lower() in PUBLIC_REPLY_TASKS


def extract_json(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    candidates = [raw]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.S | re.I)
    if fenced:
        candidates.insert(0, fenced.group(1))
    first = raw.find("{")
    last = raw.rfind("}")
    if first >= 0 and last > first:
        candidates.append(raw[first : last + 1])
    for candidate in candidates:
        try:
            doc = json.loads(candidate)
        except Exception:
            continue
        if isinstance(doc, dict):
            return doc
    return None


def post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def get_json(url: str, timeout: int) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def choose_ollama_model(host: str) -> str:
    configured = str(os.environ.get("CGNK_OLLAMA_MODEL", "")).strip()
    if configured:
        return configured
    tags = get_json(host.rstrip("/") + "/api/tags", timeout=5)
    models = [str(row.get("name", "")).strip() for row in tags.get("models", []) if isinstance(row, dict)]
    for preferred in ("qwen2.5:7b-instruct", "qwen2.5:7b", "qwen2:7b", "llama3.1:8b"):
        if preferred in models:
            return preferred
    return models[0] if models else ""


def _call_command(task: str, system: str, prompt: str, timeout: int) -> dict[str, Any]:
    cmd = str(os.environ.get("CGNK_LOCAL_MODEL_CMD", "")).strip()
    if not cmd:
        return {"ok": False, "provider": "command", "error": "CGNK_LOCAL_MODEL_CMD not configured"}
    payload = {"task": task, "system": system, "prompt": prompt}
    try:
        proc = subprocess.run(
            cmd,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            shell=True,
            cwd=str(ROOT),
            timeout=max(5, min(int(timeout), 120)),
        )
    except Exception as exc:
        return {"ok": False, "provider": "command", "error": str(exc)}
    if proc.returncode != 0:
        return {"ok": False, "provider": "command", "error": proc.stderr.strip()[:500]}
    return {"ok": True, "provider": "command", "text": proc.stdout.strip()}


def _call_ollama(task: str, system: str, prompt: str, timeout: int) -> dict[str, Any]:
    host = str(os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).strip().rstrip("/")
    try:
        model = choose_ollama_model(host)
    except (urllib.error.URLError, TimeoutError, ConnectionError, ConnectionResetError, json.JSONDecodeError) as exc:
        return {"ok": False, "provider": "ollama", "error": f"ollama unavailable: {exc}"}
    if not model:
        return {"ok": False, "provider": "ollama", "error": "no ollama models installed"}
    full_prompt = f"{system}\n\nTask: {task}\n\n{prompt}"
    try:
        doc = post_json(
            host + "/api/generate",
            {
                "model": model,
                "prompt": full_prompt,
                "stream": False,
                "options": {"temperature": local_model_temperature(task)},
            },
            timeout=max(5, min(int(timeout), 120)),
        )
    except (urllib.error.URLError, TimeoutError, ConnectionError, ConnectionResetError, json.JSONDecodeError) as exc:
        return {"ok": False, "provider": "ollama", "model": model, "error": f"ollama request failed: {exc}"}
    text = str(doc.get("response", "")).strip()
    if not text:
        return {"ok": False, "provider": "ollama", "model": model, "error": "ollama returned empty response"}
    return {"ok": True, "provider": "ollama", "model": model, "text": text}


def local_model_temperature(task: str) -> float:
    raw = str(os.environ.get("CGNK_LOCAL_MODEL_TEMPERATURE", "")).strip()
    if raw:
        try:
            return max(0.0, min(float(raw), 1.2))
        except ValueError:
            pass
    if task_is_public_reply_only(task):
        return 0.65
    return 0.1


def call_text_task(task: str, system: str, prompt: str, timeout: int) -> dict[str, Any]:
    if not task_enabled(task):
        return {"ok": False, "provider": "none", "error": f"local model disabled for task: {task}"}
    if str(os.environ.get("CGNK_LOCAL_MODEL_CMD", "")).strip():
        result = _call_command(task, system, prompt, timeout)
        if result.get("ok"):
            return result
    return _call_ollama(task, system, prompt, timeout)


def call_json_task(task: str, system: str, prompt: str, timeout: int) -> dict[str, Any]:
    result = call_text_task(task, system, prompt, timeout)
    if not result.get("ok"):
        return result
    doc = extract_json(str(result.get("text", "")))
    if doc is None:
        result["ok"] = False
        result["error"] = "local model returned non-json"
        result["preview"] = str(result.get("text", ""))[:500]
        return result
    result["json"] = doc
    return result
