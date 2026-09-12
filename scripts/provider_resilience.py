#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

try:
    import check_connectivity
    from pipeline_contracts import base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts import check_connectivity
    from scripts.pipeline_contracts import base_result


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "provider_resilience.json"
DEFAULT_REPORT = ROOT / "examples" / "test_results" / "provider_health_report.json"
DEFAULT_CONNECTIVITY_REPORT = ROOT / "examples" / "test_results" / "connectivity_check_result.json"

MIN_PROJECT_CONTEXT_TOKENS = 32_768
MIN_PROJECT_OUTPUT_TOKENS = 1_200

PROVIDER_OK = "PROVIDER_OK"
PROVIDER_QUOTA_EXCEEDED = "PROVIDER_QUOTA_EXCEEDED"
PROVIDER_TRANSPORT_UNSTABLE = "PROVIDER_TRANSPORT_UNSTABLE"
PROVIDER_AUTH_FAILED = "PROVIDER_AUTH_FAILED"
PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
RETRYABLE_STATUSES = {PROVIDER_TRANSPORT_UNSTABLE, PROVIDER_RATE_LIMITED}
BLOCK_LIVE_STATUSES = {PROVIDER_QUOTA_EXCEEDED, PROVIDER_AUTH_FAILED, PROVIDER_UNAVAILABLE}


DEFAULT_PROVIDER_CONFIG: dict[str, Any] = {
    "providers": [
        {
            "name": "primary",
            "base_url": "",
            "models": {"small": "gpt-5.4-nano", "large": "gpt-5.5"},
            "quota_required": True,
        },
        {
            "name": "backup",
            "base_url": "",
            "models": {"small": "", "large": ""},
            "enabled": False,
        },
    ]
}

DASHSCOPE_MODEL_CANDIDATES: list[dict[str, Any]] = [
    {"model": "qwen3.7-plus", "role": "large", "priority": 10, "max_output_tokens": 3_000},
    {"model": "qwen3.7-flash", "role": "small", "priority": 20, "max_output_tokens": 5_000},
    {"model": "qwen3.8-flash", "role": "large", "priority": 30, "max_output_tokens": 1_500},
    {"model": "qwen3.6-plus", "role": "large", "priority": 40, "max_output_tokens": 5_000},
    {"model": "qwen3.5-flash", "role": "small", "priority": 50, "max_output_tokens": 5_000},
    {"model": "qwen-plus", "role": "large", "priority": 60, "max_output_tokens": 5_000},
    {"model": "qwen-flash", "role": "small", "priority": 70, "max_output_tokens": 5_000},
]

GPTSAPI_MODEL_CANDIDATES: list[dict[str, Any]] = [
    {"model": "gpt-5.5", "role": "large", "priority": 10},
    {"model": "gpt-5.4-nano", "role": "small", "priority": 20},
]


@dataclass(frozen=True)
class ProviderProbe:
    name: str
    status: str = PROVIDER_OK
    quota_remaining: int | None = None
    reason: str = ""
    retryable: bool = False


def read_json(path: pathlib.Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def write_json(path: pathlib.Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_config(path: pathlib.Path | None = None) -> dict[str, Any]:
    if path and path.exists():
        loaded = read_json(path)
        if loaded:
            return loaded
    if DEFAULT_CONFIG.exists():
        loaded = read_json(DEFAULT_CONFIG)
        if loaded:
            return loaded
    config = json.loads(json.dumps(DEFAULT_PROVIDER_CONFIG))
    credentials = check_connectivity._resolve_api_credentials()
    base_url = str(credentials.get("base_url") or "")
    primary = config["providers"][0]
    primary["base_url"] = base_url
    if check_connectivity._is_alibaba_model_studio_base_url(base_url):
        primary["models"] = {"small": "qwen3.7-flash", "large": "qwen3.7-plus"}
        primary["model_candidates"] = json.loads(json.dumps(DASHSCOPE_MODEL_CANDIDATES))
    elif check_connectivity._is_gptsapi_base_url(base_url):
        primary["model_candidates"] = json.loads(json.dumps(GPTSAPI_MODEL_CANDIDATES))
    return config


def _model_capability_defaults(candidate: dict[str, Any]) -> dict[str, Any]:
    role = str(candidate.get("role") or "large").strip().lower()
    return {
        "structured_output_capable": bool(candidate.get("structured_output_capable", True)),
        "max_output_tokens": int(candidate.get("max_output_tokens", 32_768 if role == "large" else 16_384) or 0),
        "context_length": int(candidate.get("context_length", 131_072) or 0),
        "project_generation_suitable": bool(candidate.get("project_generation_suitable", True)),
        "repair_generation_suitable": bool(candidate.get("repair_generation_suitable", True)),
    }


def _provider_model_candidates(provider: dict[str, Any], requested_model: str = "") -> list[dict[str, Any]]:
    requested = str(requested_model or "").strip()
    configured = provider.get("model_candidates")
    candidates: list[dict[str, Any]] = []
    if isinstance(configured, list):
        for index, raw in enumerate(configured):
            item = {"model": raw} if isinstance(raw, str) else dict(raw) if isinstance(raw, dict) else {}
            model = str(item.get("model") or item.get("name") or "").strip()
            if model:
                item.update(model=model, role=str(item.get("role") or "large"), priority=int(item.get("priority", index + 1)))
                candidates.append(item)
    if not candidates:
        models = provider.get("models", {}) if isinstance(provider.get("models"), dict) else {}
        for index, (role, model) in enumerate(models.items()):
            name = str(model or "").strip()
            if name:
                candidates.append({"model": name, "role": str(role or "large"), "priority": index + 1})
    if requested:
        matching = [item for item in candidates if item["model"] == requested]
        return matching or [{"model": requested, "role": "large", "priority": 0}]
    return candidates


def _candidate_satisfies_contract(candidate: dict[str, Any], required_role: str) -> tuple[bool, list[str]]:
    capabilities = _model_capability_defaults(candidate)
    reasons: list[str] = []
    if not capabilities["structured_output_capable"]:
        reasons.append("structured_output_unsupported")
    if capabilities["max_output_tokens"] < MIN_PROJECT_OUTPUT_TOKENS:
        reasons.append("max_output_insufficient")
    if capabilities["context_length"] < MIN_PROJECT_CONTEXT_TOKENS:
        reasons.append("context_length_insufficient")
    if required_role == "repair" and not capabilities["repair_generation_suitable"]:
        reasons.append("repair_generation_unsuitable")
    if required_role != "repair" and not capabilities["project_generation_suitable"]:
        reasons.append("project_generation_unsuitable")
    return not reasons, reasons


def _env_status(provider_name: str) -> str:
    key = f"CGNK_PROVIDER_{provider_name.upper()}_STATUS"
    status = os.environ.get(key, "").strip().upper()
    allowed = {
        PROVIDER_OK,
        PROVIDER_QUOTA_EXCEEDED,
        PROVIDER_TRANSPORT_UNSTABLE,
        PROVIDER_AUTH_FAILED,
        PROVIDER_RATE_LIMITED,
        PROVIDER_UNAVAILABLE,
    }
    return status if status in allowed else ""


def _fresh_connectivity_doc(path: pathlib.Path, *, max_age_seconds: int = 21600) -> dict[str, Any]:
    doc = read_json(path)
    if not doc:
        return {}
    created = str(doc.get("created_at") or "")
    if not created:
        return doc
    try:
        created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - created_at.astimezone(timezone.utc)).total_seconds()
    except Exception:
        return doc
    return doc if age <= max_age_seconds else {}


def _status_from_connectivity_report(path: pathlib.Path) -> ProviderProbe | None:
    doc = _fresh_connectivity_doc(path)
    api = doc.get("api", {}) if isinstance(doc.get("api"), dict) else {}
    if not api or not api.get("live"):
        return None
    if doc.get("ok") is True or api.get("ok") is True:
        return ProviderProbe(name="primary", status=PROVIDER_OK, reason="live connectivity ok")
    error = str(api.get("error") or "").lower()
    if "key usage limit exceeded" in error or ("http 403" in error and "usage" in error):
        return ProviderProbe(name="primary", status=PROVIDER_QUOTA_EXCEEDED, reason="live connectivity quota exceeded")
    if "401" in error or "unauthorized" in error or "auth" in error:
        return ProviderProbe(name="primary", status=PROVIDER_AUTH_FAILED, reason="live connectivity auth failed")
    if "429" in error or "rate" in error:
        return ProviderProbe(name="primary", status=PROVIDER_RATE_LIMITED, reason="live connectivity rate limited", retryable=True)
    if any(token in error for token in ("timeout", "connection", "ssl", "502", "503", "504", "522")):
        return ProviderProbe(name="primary", status=PROVIDER_TRANSPORT_UNSTABLE, reason="live connectivity transport unstable", retryable=True)
    if error:
        return ProviderProbe(name="primary", status=PROVIDER_UNAVAILABLE, reason="live connectivity unavailable")
    return None


def _provider_enabled(provider: dict[str, Any]) -> bool:
    if provider.get("enabled") is False:
        return False
    name = str(provider.get("name") or "").strip()
    return bool(name)


def estimate_cost_tokens(goal: str, model: str = "") -> dict[str, Any]:
    words = max(1, len(str(goal or "").split()))
    prompt_tokens = max(512, words * 2)
    completion_tokens = 12000 if "large" in model.lower() or "5.5" in model else 6000
    return {
        "prompt_tokens_estimate": prompt_tokens,
        "completion_tokens_estimate": completion_tokens,
        "total_tokens_estimate": prompt_tokens + completion_tokens,
        "model": model,
    }


def default_probe(provider: dict[str, Any]) -> ProviderProbe:
    name = str(provider.get("name") or "provider")
    status = _env_status(name)
    if status:
        return ProviderProbe(name=name, status=status, reason=f"env:{status}", retryable=status in RETRYABLE_STATUSES)
    report_path = pathlib.Path(str(provider.get("connectivity_report") or DEFAULT_CONNECTIVITY_REPORT))
    if name == "primary" and report_path.exists():
        connectivity = _status_from_connectivity_report(report_path)
        if connectivity is not None:
            return ProviderProbe(name=name, status=connectivity.status, reason=connectivity.reason, retryable=connectivity.retryable)
    quota_required = bool(provider.get("quota_required"))
    api_key_env = str(provider.get("api_key_env") or "OPENAI_API_KEY")
    credential_present = bool(os.environ.get(api_key_env))
    if name == "primary" and api_key_env == "OPENAI_API_KEY":
        credential_present = credential_present or bool(
            check_connectivity._resolve_api_credentials().get("api_key")
        )
    if quota_required and not credential_present:
        return ProviderProbe(name=name, status=PROVIDER_UNAVAILABLE, reason=f"{api_key_env} missing")
    return ProviderProbe(name=name, status=PROVIDER_OK, reason="preflight ok")


def _status_from_api_result(api: dict[str, Any]) -> tuple[str, str, bool]:
    if api.get("ok") is True:
        return PROVIDER_OK, "live structured-output probe ok", False
    error = str(api.get("error") or "")
    lowered = error.lower()
    if any(marker in lowered for marker in ("free quota exhausted", "key usage limit exceeded", "insufficient_quota")):
        return PROVIDER_QUOTA_EXCEEDED, error, False
    if "http 403" in lowered:
        return PROVIDER_QUOTA_EXCEEDED, error, False
    if any(marker in lowered for marker in ("http 401", "unauthorized", "authentication")):
        return PROVIDER_AUTH_FAILED, error, False
    if "http 429" in lowered or "rate limit" in lowered:
        return PROVIDER_RATE_LIMITED, error, True
    if any(marker in lowered for marker in ("timeout", "timed out", "ssl", "connection", "http 502", "http 503", "http 504")):
        return PROVIDER_TRANSPORT_UNSTABLE, error, True
    return PROVIDER_UNAVAILABLE, error or "provider model unavailable", False


def default_model_probe(provider: dict[str, Any], candidate: dict[str, Any], timeout: int = 20) -> dict[str, Any]:
    model = str(candidate.get("model") or "")
    api = check_connectivity.check_api(True, timeout, model, structured=True)
    status, reason, retryable = _status_from_api_result(api)
    if status == PROVIDER_OK and api.get("structured_output_valid") is not True:
        status = PROVIDER_UNAVAILABLE
        reason = "structured output probe returned non-JSON content"
    return {
        "name": str(provider.get("name") or "provider"),
        "model": model,
        "status": status,
        "reason": reason,
        "retryable": retryable,
        "endpoint": str(api.get("endpoint") or provider.get("base_url") or ""),
        "auth_ok": status != PROVIDER_AUTH_FAILED and bool(api.get("configured")),
        "quota_ok": status != PROVIDER_QUOTA_EXCEEDED,
        "transport_ok": status not in {PROVIDER_TRANSPORT_UNSTABLE},
        "structured_output_verified": bool(api.get("structured_output_valid")),
        "request_id": str(api.get("request_id") or ""),
    }


def provider_preflight(
    config: dict[str, Any] | None = None,
    *,
    goal: str = "",
    probe: Callable[[dict[str, Any]], ProviderProbe | dict[str, Any]] | None = None,
    model_probe: Callable[[dict[str, Any], dict[str, Any]], ProviderProbe | dict[str, Any]] | None = None,
    live: bool = False,
    requested_model: str = "",
    required_role: str = "generation",
    timeout: int = 20,
) -> dict[str, Any]:
    cfg = config or load_config()
    providers = [item for item in cfg.get("providers", []) if isinstance(item, dict) and _provider_enabled(item)]
    results: list[dict[str, Any]] = []
    candidates_checked: list[dict[str, Any]] = []
    legacy_probe = probe or default_probe

    for provider_index, provider in enumerate(providers):
        models = provider.get("models", {}) if isinstance(provider.get("models"), dict) else {}
        candidates = _provider_model_candidates(provider, requested_model)
        provider_rows: list[dict[str, Any]] = []
        provider_probe_doc: dict[str, Any] | None = None
        if not live and model_probe is None:
            raw = legacy_probe(provider)
            if isinstance(raw, ProviderProbe):
                provider_probe_doc = {
                    "name": raw.name,
                    "status": raw.status,
                    "quota_remaining": raw.quota_remaining,
                    "reason": raw.reason,
                    "retryable": raw.retryable,
                }
            else:
                provider_probe_doc = dict(raw)
        for model_index, candidate in enumerate(candidates):
            capability_ok, capability_reasons = _candidate_satisfies_contract(candidate, required_role)
            if provider_probe_doc is not None:
                probe_doc = dict(provider_probe_doc)
            else:
                probe_fn = model_probe or (lambda p, c: default_model_probe(p, c, timeout=timeout))
                raw = probe_fn(provider, candidate)
                if isinstance(raw, ProviderProbe):
                    probe_doc = {
                        "name": raw.name,
                        "status": raw.status,
                        "quota_remaining": raw.quota_remaining,
                        "reason": raw.reason,
                        "retryable": raw.retryable,
                    }
                else:
                    probe_doc = dict(raw)
            capability = _model_capability_defaults(candidate)
            row = {
                "provider": str(probe_doc.get("name") or provider.get("name") or "provider"),
                "model": str(candidate.get("model") or ""),
                "role": str(candidate.get("role") or "large"),
                "status": str(probe_doc.get("status") or PROVIDER_UNAVAILABLE),
                "reason": str(probe_doc.get("reason") or ""),
                "retryable": bool(probe_doc.get("retryable")),
                "endpoint": str(probe_doc.get("endpoint") or provider.get("base_url") or ""),
                "auth_ok": bool(probe_doc.get("auth_ok", probe_doc.get("status") != PROVIDER_AUTH_FAILED)),
                "quota_ok": bool(probe_doc.get("quota_ok", probe_doc.get("status") != PROVIDER_QUOTA_EXCEEDED)),
                "transport_ok": bool(probe_doc.get("transport_ok", probe_doc.get("status") not in {PROVIDER_TRANSPORT_UNSTABLE})),
                "structured_output_verified": bool(probe_doc.get("structured_output_verified", not live)),
                "structured_output_capable": capability["structured_output_capable"],
                "max_output_tokens": capability["max_output_tokens"],
                "max_output_enough": capability["max_output_tokens"] >= MIN_PROJECT_OUTPUT_TOKENS,
                "context_length": capability["context_length"],
                "context_length_enough": capability["context_length"] >= MIN_PROJECT_CONTEXT_TOKENS,
                "project_generation_suitable": capability["project_generation_suitable"],
                "repair_generation_suitable": capability["repair_generation_suitable"],
                "priority": int(candidate.get("priority", model_index + 1)),
                "provider_index": provider_index,
                "model_index": model_index,
                "token_cost_estimate": estimate_cost_tokens(goal, str(candidate.get("model") or "")),
            }
            if not capability_ok:
                row["status"] = PROVIDER_UNAVAILABLE
                row["reason"] = ";".join(capability_reasons)
            provider_rows.append(row)
            candidates_checked.append(row)
        provider_statuses = [row["status"] for row in provider_rows]
        results.append(
            {
                "name": str(provider.get("name") or "provider"),
                "status": PROVIDER_OK if PROVIDER_OK in provider_statuses else (provider_statuses[0] if provider_statuses else PROVIDER_UNAVAILABLE),
                "models": dict(models),
                "candidates": provider_rows,
            }
        )

    preferred_role = "small" if required_role == "repair" else "large"
    eligible = [row for row in candidates_checked if row["status"] == PROVIDER_OK]
    eligible.sort(key=lambda row: (row["role"] != preferred_role, row["provider_index"], row["priority"], row["model_index"]))
    selected_row = eligible[0] if eligible else None
    selected: dict[str, Any] | None = None
    if selected_row:
        provider = providers[int(selected_row["provider_index"])]
        selected = {
            "name": selected_row["provider"],
            "model": selected_row["model"],
            "role": selected_row["role"],
            "models": dict(provider.get("models", {})) if isinstance(provider.get("models"), dict) else {},
            "base_url": str(provider.get("base_url") or selected_row["endpoint"]),
            "endpoint": selected_row["endpoint"],
        }

    if selected is not None:
        status = PROVIDER_OK
        live_generation_allowed = True
        commercial_blocker = ""
    else:
        statuses = {str(row.get("status")) for row in candidates_checked}
        status = PROVIDER_QUOTA_EXCEEDED if statuses == {PROVIDER_QUOTA_EXCEEDED} else PROVIDER_UNAVAILABLE
        live_generation_allowed = False
        commercial_blocker = "provider_quota" if status == PROVIDER_QUOTA_EXCEEDED else "provider_unavailable"

    fallback_used = bool(selected_row and (selected_row["provider_index"] > 0 or selected_row["model_index"] > 0))
    report = {
        "status": status,
        "selected_provider": selected,
        "selected_model": selected.get("model", "") if selected else "",
        "selected_role": selected.get("role", "") if selected else "",
        "endpoint": selected.get("endpoint", "") if selected else "",
        "fallback_used": fallback_used,
        "providers": results,
        "candidates_checked": candidates_checked,
        "unavailable_models": [row["model"] for row in candidates_checked if row["status"] != PROVIDER_OK],
        "all_provider_blocked": selected is None,
        "blocker_reason": "" if selected else "NO_AVAILABLE_PROVIDER_MODEL",
        "live_generation_allowed": live_generation_allowed,
        "commercial_blocker": commercial_blocker,
        "user_visible_status": "当前模型额度不足，请更换 provider 或稍后继续。" if status == PROVIDER_QUOTA_EXCEEDED and not selected else "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return base_result(
        status="pass" if selected else ("warning" if status in RETRYABLE_STATUSES else "fail"),
        verdict=status,
        blockers=[commercial_blocker] if commercial_blocker else [],
        warnings=["provider fallback selected"] if fallback_used else [],
        metadata=report,
    )


def retryable_provider_call(call: Callable[[], Any], *, attempts: int = 3, delay_seconds: float = 0.1) -> dict[str, Any]:
    errors: list[str] = []
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return base_result(status="pass", verdict="provider_call_ok", metadata={"attempt": attempt, "result": call()})
        except TimeoutError as exc:
            errors.append(str(exc) or "timeout")
            if attempt < attempts:
                time.sleep(delay_seconds)
                continue
            return base_result(status="warning", verdict=PROVIDER_TRANSPORT_UNSTABLE, warnings=errors, metadata={"attempts": attempt, "retryable": True})
        except ConnectionError as exc:
            errors.append(str(exc) or "connection error")
            if attempt < attempts:
                time.sleep(delay_seconds)
                continue
            return base_result(status="warning", verdict=PROVIDER_TRANSPORT_UNSTABLE, warnings=errors, metadata={"attempts": attempt, "retryable": True})
        except Exception as exc:
            return base_result(status="fail", verdict=PROVIDER_UNAVAILABLE, blockers=[str(exc)], metadata={"attempt": attempt, "retryable": False})
    return base_result(status="warning", verdict=PROVIDER_TRANSPORT_UNSTABLE, warnings=errors, metadata={"attempts": attempts, "retryable": True})


def write_health_report(report: dict[str, Any], path: pathlib.Path = DEFAULT_REPORT) -> pathlib.Path:
    write_json(path, report)
    return path


def load_fresh_health_report(path: pathlib.Path = DEFAULT_REPORT, *, max_age_seconds: int = 21_600) -> dict[str, Any]:
    report = read_json(path)
    metadata = report.get("metadata", {}) if isinstance(report.get("metadata"), dict) else {}
    created = str(metadata.get("created_at") or "")
    if not created:
        return {}
    try:
        created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - created_at.astimezone(timezone.utc)).total_seconds()
    except Exception:
        return {}
    return report if age <= max_age_seconds else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="")
    parser.add_argument("--goal", default="")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--model", default="", help="Optional explicit model; omit to auto-select.")
    parser.add_argument("--role", choices=("generation", "repair"), default="generation")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    config = load_config(pathlib.Path(args.config)) if args.config else load_config()
    report = provider_preflight(
        config,
        goal=args.goal,
        live=args.live,
        requested_model=args.model,
        required_role=args.role,
        timeout=max(1, args.timeout),
    )
    write_health_report(report, pathlib.Path(args.report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["metadata"]["live_generation_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
