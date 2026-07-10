from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

try:
    import check_connectivity
    import provider_api_smoke
    from agent_tree_contracts import write_json
except ModuleNotFoundError:  # pragma: no cover
    from scripts import check_connectivity, provider_api_smoke
    from scripts.agent_tree_contracts import write_json


SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]+", re.I),
    re.compile(r"(api[_-]?key['\"]?\s*[:=]\s*['\"])[^'\"]+", re.I),
]

PROVIDER_MODEL_UNSUPPORTED_PATTERNS = [
    "this model is not supported",
    "x-openai-internal-codex-responses-lite",
    "responses lite",
]


def redact_secret(text: str) -> str:
    redacted = str(text or "")
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + "<redacted>", redacted)
    return redacted


def classify_provider_error(error: str) -> dict[str, Any]:
    safe_error = redact_secret(error)
    lowered = safe_error.lower()
    if any(pattern in lowered for pattern in PROVIDER_MODEL_UNSUPPORTED_PATTERNS):
        failure_type = "provider_model_unsupported"
        reason = "Provider/model invocation is unsupported in the current Codex Responses Lite environment."
    else:
        failure_type = "provider_unavailable"
        reason = "Provider invocation failed before a usable leaf output was produced."
    return {
        "classification": "provider_unavailable",
        "failure_type": failure_type,
        "verdict": "BLOCKED",
        "not_proven": True,
        "fake_success": False,
        "public_safe_error": safe_error,
        "reason": reason,
    }


def call_responses_provider(
    *,
    base_url: str,
    token: str,
    payload: dict[str, Any],
    timeout: int,
    max_attempts: int = 3,
    retry_delay: float = 0.5,
) -> tuple[dict[str, Any] | None, str, int]:
    transport = check_connectivity._post_json_with_retry(
        check_connectivity._responses_endpoint(base_url),
        payload,
        token,
        timeout,
        max_attempts=max_attempts,
        base_delay_sec=retry_delay,
    )
    return transport.doc, redact_secret(transport.error), len(transport.attempts)


def provider_readiness(*, out_dir: str | pathlib.Path, model: str = "gpt-5.4-nano", smoke: bool = True, timeout: int = 45) -> dict[str, Any]:
    out = pathlib.Path(out_dir)
    creds = check_connectivity._resolve_api_credentials()
    token = str(creds.get("api_key", "")).strip()
    base_url = str(creds.get("base_url", "")).strip()
    result: dict[str, Any] = {
        "provider_ready": False,
        "provider_mode": "real_provider_api",
        "model": model,
        "credential_present": bool(token),
        "base_url_present": bool(base_url),
        "smoke_attempted": False,
        "smoke_status": "not_attempted",
        "public_safe_error": "",
        "raw_error_redacted": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if not token or not base_url:
        result["smoke_status"] = "skipped_missing_credentials"
        result["public_safe_error"] = "provider credentials are not fully configured"
    elif smoke:
        result["smoke_attempted"] = True
        try:
            payload = {
                "model": model,
                "input": [{"role": "user", "content": [{"type": "input_text", "text": "Return exactly: {\"smoke\":true}"}]}],
                "max_tokens": 80,
            }
            doc, error, attempts = call_responses_provider(
                base_url=base_url,
                token=token,
                payload=payload,
                timeout=timeout,
            )
            text = check_connectivity._extract_text(doc or {}) if doc else ""
            smoke_result = {
                "ok": bool(doc and "\"smoke\":true" in text.replace(" ", "")),
                "error_summary": error,
                "response_preview": text[:120],
                "attempts": attempts,
            }
        except Exception as exc:
            smoke_result = {"ok": False, "error_summary": redact_secret(str(exc))}
        result["smoke_status"] = "pass" if smoke_result.get("ok") else "fail"
        result["provider_ready"] = bool(smoke_result.get("ok"))
        result["smoke_attempts"] = int(smoke_result.get("attempts") or 1)
        result["public_safe_error"] = "" if result["provider_ready"] else redact_secret(str(smoke_result.get("error_summary") or smoke_result.get("error_code") or "provider smoke failed"))
    else:
        result["smoke_status"] = "skipped"
        result["public_safe_error"] = "smoke disabled"

    write_json(out / "provider_readiness.json", result)
    md = [
        "# Provider Readiness",
        "",
        f"- provider_ready: {result['provider_ready']}",
        f"- provider_mode: {result['provider_mode']}",
        f"- model: {model}",
        f"- credential_present: {result['credential_present']}",
        f"- base_url_present: {result['base_url_present']}",
        f"- smoke_attempted: {result['smoke_attempted']}",
        f"- smoke_status: {result['smoke_status']}",
        f"- public_safe_error: {result['public_safe_error']}",
    ]
    (out / "provider_readiness.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return result


def build_leaf_provider_prompt(*, agent_id: str, allowed_files: list[str], forbidden_files: list[str], user_goal: str) -> str:
    leaf_contracts = {
        "document_import_leaf": (
            "For document_import_leaf, expose a top-level function `import_document(title, content)` returning a dict with title, content, and status/id fields. "
            "Include a pytest file that imports and tests it.\n"
        ),
        "search_service_leaf": (
            "For search_service_leaf, expose a top-level function `search_documents(documents, query)` and include a pytest file that imports and tests it.\n"
        ),
        "model_adapter_leaf": (
            "For model_adapter_leaf, expose a top-level function `adapter_status(config=None)` returning a dict. "
            "With empty config it must not claim real inference and should include a limit mentioning missing model or endpoint. Include a pytest file that imports and tests it.\n"
        ),
        "task_service_leaf": (
            "For task_service_leaf, expose a top-level function `create_task(title)` returning a dict with title and status='open'. "
            "Include a pytest file that imports and tests it.\n"
        ),
        "report_service_leaf": (
            "For report_service_leaf, expose a top-level function `build_report(documents, tasks)` returning a dict with document_count and task_count. "
            "Include a pytest file that imports and tests it.\n"
        ),
        "dashboard_page_leaf": (
            "For dashboard_page_leaf, generate a complete HTML dashboard template for Local AI Knowledge Studio. "
            "It must include dashboard, documents, search, tasks, reports, and settings navigation text.\n"
        ),
        "documents_page_leaf": (
            "For documents_page_leaf, generate a complete HTML documents template focused on document import and knowledge base items. "
            "It must include documents, import, knowledge, search, tasks, reports, and settings navigation text.\n"
        ),
        "search_page_leaf": (
            "For search_page_leaf, generate a complete HTML search template focused on querying the local knowledge base. "
            "It must include search, query, results, documents, tasks, reports, and settings navigation text.\n"
        ),
        "tasks_page_leaf": (
            "For tasks_page_leaf, generate a complete HTML tasks template focused on follow-up task tracking. "
            "It must include tasks, status, documents, search, reports, and settings navigation text.\n"
        ),
        "reports_page_leaf": (
            "For reports_page_leaf, generate a complete HTML reports template focused on generated reports and summaries. "
            "It must include reports, summary, documents, search, tasks, and settings navigation text.\n"
        ),
        "settings_page_leaf": (
            "For settings_page_leaf, generate a complete HTML settings template focused on local model configuration. "
            "It must include settings, local model, documents, search, tasks, and reports navigation text.\n"
        ),
        "smoke_test_leaf": (
            "For smoke_test_leaf, generate a pytest smoke test file only. "
            "It may import app.main or app.routes after integration, and must not create application code.\n"
        ),
        "backend_tests_leaf": (
            "For backend_tests_leaf, generate a pytest integration test file only. "
            "It should exercise document import, search, task, report, and local model adapter service behavior after integration.\n"
        ),
        "ui_route_tests_leaf": (
            "For ui_route_tests_leaf, generate a pytest route test file only. "
            "It should verify dashboard, documents, search, tasks, reports, and settings route/page rendering after integration.\n"
        ),
    }
    leaf_specific = leaf_contracts.get(agent_id, "")
    return (
        f"You are {agent_id}.\n"
        "You can generate only the files listed in allowed_files.\n"
        "You cannot generate the whole project.\n"
        "You cannot modify README, app/main.py, requirements.txt, delivery_manifest.json, final_project_bundle.zip, or app/templates/* unless explicitly allowed.\n"
        "You cannot claim delivery completion or test completion.\n"
        "Return strict JSON only with shape {\"files\":[{\"path\":\"...\",\"content\":\"...\"}]}.\n"
        "You must include every allowed file exactly once. Missing any allowed file is a failed leaf.\n"
        f"{leaf_specific}"
        f"User goal: {user_goal}\n"
        f"allowed_files: {json.dumps(allowed_files, ensure_ascii=False)}\n"
        f"forbidden_files: {json.dumps(forbidden_files, ensure_ascii=False)}\n"
    )


def build_provider_request(*, model: str, prompt: str, base_url: str = "") -> dict[str, Any]:
    return {
        "model": model,
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Return strict JSON only. No markdown.\n\n" + prompt,
                    }
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": 5000,
        "base_url_present": bool(base_url),
    }


def save_redacted_provider_request(*, out_dir: str | pathlib.Path, request_doc: dict[str, Any], prompt: str) -> None:
    out = pathlib.Path(out_dir)
    safe = json.loads(redact_secret(json.dumps(request_doc, ensure_ascii=False)))
    write_json(out / "provider_request_redacted.json", safe)
    (out / "provider_prompt.md").write_text(redact_secret(prompt), encoding="utf-8")
