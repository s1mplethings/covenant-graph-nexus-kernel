from __future__ import annotations

import pathlib
import re
from typing import Any

try:
    from agent_tree_contracts import DEFAULT_EVAL_DIR, contains_forbidden_terms, write_json
except ModuleNotFoundError:  # pragma: no cover
    from scripts.agent_tree_contracts import DEFAULT_EVAL_DIR, contains_forbidden_terms, write_json


STAGE_DEFAULTS: dict[str, dict[str, list[str]]] = {
    "backend_services": {
        "required_files": [
            "app/services/document_service.py",
            "app/services/search_service.py",
            "app/services/model_adapter.py",
            "app/services/task_service.py",
            "app/services/report_service.py",
        ],
        "verification": ["service_files_exist", "python_import_smoke"],
    },
    "frontend_views": {
        "required_files": [
            "app/templates/dashboard.html",
            "app/templates/documents.html",
            "app/templates/search.html",
            "app/templates/tasks.html",
            "app/templates/reports.html",
            "app/templates/settings.html",
        ],
        "verification": ["view_count_ge_5", "frontend_entrypoint_exists"],
    },
}


def sanitize_context_text(text: str, forbidden_terms: list[str]) -> str:
    cleaned = text
    for phrase in ("视频素材", "鉴挂判别", "背景立绘", "video material workbench", "image generation demo"):
        cleaned = re.sub(re.escape(phrase), "", cleaned, flags=re.IGNORECASE)
    for term in forbidden_terms:
        cleaned = re.sub(re.escape(term), "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(\+\s*){2,}", "+ ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" +")
    return cleaned.strip()


def reduce_context(
    shared_context: dict[str, Any],
    *,
    agent_id: str,
    stage: str,
    raw_context: str = "",
    required_files: list[str] | None = None,
    verification: list[str] | None = None,
) -> dict[str, Any]:
    forbidden = list(shared_context.get("forbidden_context_terms") or [])
    defaults = STAGE_DEFAULTS.get(stage, {})
    sanitized = sanitize_context_text(raw_context or str(shared_context.get("user_goal", "")), forbidden)
    local_context = {
        "kind": "LocalAgentContext",
        "context_id": f"{agent_id}_context_v1",
        "agent_id": agent_id,
        "stage": stage,
        "project_name": shared_context.get("project_name", ""),
        "user_goal_summary": sanitized or shared_context.get("project_name", ""),
        "allowed_context_terms": list(shared_context.get("allowed_context_terms") or []),
        "required_files": list(required_files or defaults.get("required_files", [])),
        "interfaces": [],
        "verification": list(verification or defaults.get("verification", [])),
        "forbidden_context_terms": forbidden,
        "removed_forbidden_terms": contains_forbidden_terms(raw_context, forbidden) if raw_context else [],
    }
    return local_context


def save_local_context(context: dict[str, Any], out_dir: str | pathlib.Path = DEFAULT_EVAL_DIR) -> pathlib.Path:
    contexts = pathlib.Path(out_dir) / "local_contexts"
    return write_json(contexts / f"{context['agent_id']}.json", context)
