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
    from pipeline_contracts import base_result
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts.pipeline_contracts import base_result


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "provider_resilience.json"
DEFAULT_REPORT = ROOT / "examples" / "test_results" / "provider_health_report.json"
DEFAULT_CONNECTIVITY_REPORT = ROOT / "examples" / "test_results" / "connectivity_check_result.json"

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
    return json.loads(json.dumps(DEFAULT_PROVIDER_CONFIG))


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
    if quota_required and not os.environ.get(api_key_env):
        return ProviderProbe(name=name, status=PROVIDER_UNAVAILABLE, reason=f"{api_key_env} missing")
    return ProviderProbe(name=name, status=PROVIDER_OK, reason="preflight ok")


def provider_preflight(
    config: dict[str, Any] | None = None,
    *,
    goal: str = "",
    probe: Callable[[dict[str, Any]], ProviderProbe | dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    probe_fn = probe or default_probe
    providers = [item for item in cfg.get("providers", []) if isinstance(item, dict) and _provider_enabled(item)]
    results: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    primary_block_reason = ""

    for provider in providers:
        raw_probe = probe_fn(provider)
        if isinstance(raw_probe, ProviderProbe):
            probe_doc = {
                "name": raw_probe.name,
                "status": raw_probe.status,
                "quota_remaining": raw_probe.quota_remaining,
                "reason": raw_probe.reason,
                "retryable": raw_probe.retryable,
            }
        else:
            probe_doc = dict(raw_probe)
            probe_doc.setdefault("name", provider.get("name", "provider"))
            probe_doc.setdefault("status", PROVIDER_UNAVAILABLE)
            probe_doc.setdefault("retryable", probe_doc.get("status") in RETRYABLE_STATUSES)
        models = provider.get("models", {}) if isinstance(provider.get("models"), dict) else {}
        probe_doc["models"] = dict(models)
        probe_doc["token_cost_estimate"] = estimate_cost_tokens(goal, str(models.get("large") or models.get("small") or ""))
        results.append(probe_doc)
        if probe_doc["status"] == PROVIDER_OK and selected is None:
            selected = {"name": probe_doc["name"], "models": dict(models), "base_url": provider.get("base_url", "")}
        elif selected is None and not primary_block_reason:
            primary_block_reason = str(probe_doc["status"])

    if selected:
        status = PROVIDER_OK
        live_generation_allowed = True
        commercial_blocker = ""
    else:
        status = primary_block_reason or PROVIDER_UNAVAILABLE
        live_generation_allowed = status not in BLOCK_LIVE_STATUSES
        commercial_blocker = "provider_quota" if status == PROVIDER_QUOTA_EXCEEDED else "provider_unavailable"

    fallback_used = bool(selected and results and selected["name"] != results[0].get("name"))
    report = {
        "status": status,
        "selected_provider": selected,
        "fallback_used": fallback_used,
        "providers": results,
        "live_generation_allowed": live_generation_allowed,
        "commercial_blocker": commercial_blocker,
        "user_visible_status": "当前模型额度不足，请更换 provider 或稍后继续。" if status == PROVIDER_QUOTA_EXCEEDED and not selected else "",
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="")
    parser.add_argument("--goal", default="")
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()
    config = load_config(pathlib.Path(args.config)) if args.config else load_config()
    report = provider_preflight(config, goal=args.goal)
    write_health_report(report, pathlib.Path(args.report))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["metadata"]["live_generation_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
