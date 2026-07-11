from __future__ import annotations

import pathlib
import re
from typing import Any


SECRET_TOKENS = ("CGKN_OPENAI_API_KEY", "CGNK_OPENAI_API_KEY", "OPENAI_API_KEY=", "api.gptsapi.net")


def _files(project: pathlib.Path) -> list[pathlib.Path]:
    return [item for item in project.rglob("*") if item.is_file()] if project.exists() else []


def _contains_any(path: pathlib.Path, tokens: tuple[str, ...]) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    lowered = text.lower()
    return any(token.lower() in lowered for token in tokens)


def evaluate_project(project_dir: str | pathlib.Path, target_project_model: dict[str, Any] | None = None) -> dict[str, Any]:
    project = pathlib.Path(project_dir)
    target = target_project_model if isinstance(target_project_model, dict) else {}
    mode = str(target.get("mode") or target.get("model_mode") or "unspecified")
    files = _files(project)
    labels = [str(item.relative_to(project)).replace("\\", "/").lower() for item in files]

    frontend_entry = next((item for item in labels if item.endswith("index.html") or item.startswith("src/app.") or "/frontend/" in item), "")
    backend_entry = next((item for item in labels if item.endswith(("app.py", "main.py", "server.js")) or "/backend/" in item), "")
    api_adapter = any("api_client" in item or "client" in item or "adapter" in item for item in labels)
    storage_layer = any("store" in item or "storage" in item or "db" in item or "sqlite" in item for item in labels)
    model_adapter = any("model_adapter" in item or "llm_adapter" in item or "local_model" in item or "model/" in item for item in labels)
    config_schema = any("config" in item or ".env.example" in item for item in labels)
    api_schema = any("openapi" in item or "api_schema" in item or "contract" in item for item in labels)
    docs = [item for item in files if item.suffix.lower() in {".md", ".txt", ".env", ".example", ".py", ".js", ".ts", ".tsx", ".jsx"}]
    leaked = [str(item.relative_to(project)) for item in docs if _contains_any(item, SECRET_TOKENS)]

    config_documented = any(_contains_any(item, ("MODEL_PATH", "LOCAL_MODEL_ENDPOINT", "model path", "endpoint")) for item in docs)
    missing_limit_documented = any(_contains_any(item, ("缺少模型", "missing model", "model file", "不能宣称真实推理")) for item in docs)

    missing: list[str] = []
    if not frontend_entry:
        missing.append("frontend_entrypoint")
    if not backend_entry:
        missing.append("backend_entrypoint")
    if not api_adapter:
        missing.append("api_client_or_adapter")
    if not storage_layer:
        missing.append("storage_layer")
    if not api_schema:
        missing.append("api_schema")
    if not config_schema:
        missing.append("config_schema")
    if mode == "local_model":
        if not model_adapter:
            missing.append("model_adapter")
        if not config_documented:
            missing.append("model_config_documented")
        if not missing_limit_documented:
            missing.append("missing_model_limit_documented")
    if leaked:
        missing.append("cgkn_provider_config_leaked")

    verdict = "PASS" if not missing else "NEEDS_REWORK" if files else "FAIL"
    return {
        "frontend": {"exists": bool(frontend_entry), "entrypoint": frontend_entry, "api_client_or_adapter": api_adapter},
        "backend": {"exists": bool(backend_entry), "entrypoint": backend_entry, "storage_layer": storage_layer, "model_adapter": model_adapter},
        "shared_contract": {"api_schema_exists": api_schema, "config_schema_exists": config_schema, "data_model_documented": storage_layer},
        "target_project_model": {
            "mode": mode,
            "adapter_exists": model_adapter,
            "config_documented": config_documented,
            "missing_model_limit_documented": missing_limit_documented,
        },
        "verdict": verdict,
        "missing": missing,
        "leaked_files": leaked,
    }
