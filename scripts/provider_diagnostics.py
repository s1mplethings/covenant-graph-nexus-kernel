from __future__ import annotations

import argparse
import json
import pathlib
import sys
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.providers import (  # noqa: E402
    DeepSeekConnector, GrokConnector, ProviderConnectionError, QwenConnector,
)


CONNECTOR_TYPES = {"qwen": QwenConnector, "grok": GrokConnector, "deepseek": DeepSeekConnector}
EXIT_CODES = {"ELIGIBLE": 0, "AUTH_BLOCKED": 2, "PROTOCOL_BLOCKED": 3, "MODEL_BLOCKED": 4, "BUDGET_BLOCKED": 5, "ENVIRONMENT_BLOCKED": 6, "INTERNAL_ERROR": 7}


def _profile(provider_id: str) -> dict[str, Any]:
    path = ROOT / "config" / "provider_connections" / f"{provider_id}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("provider_id") != provider_id:
        raise ValueError("Provider connection profile identity mismatch")
    return value


def _status(error_class: str, eligible: bool) -> str:
    if eligible: return "ELIGIBLE"
    if any(item in error_class for item in ("AUTH", "KEY", "CREDENTIAL")): return "AUTH_BLOCKED"
    if "MODEL" in error_class: return "MODEL_BLOCKED"
    if "BUDGET" in error_class: return "BUDGET_BLOCKED"
    if any(item in error_class for item in ("ENDPOINT", "PROTOCOL", "SCHEMA")): return "PROTOCOL_BLOCKED"
    return "ENVIRONMENT_BLOCKED"


def diagnose(provider_id: str, output_root: pathlib.Path) -> tuple[dict[str, Any], int]:
    profile = _profile(provider_id)
    try:
        connector = CONNECTOR_TYPES[provider_id](profile)
        health = connector.probe_connection()
        receipt = health.as_dict()
        receipt["connection_snapshot"] = connector.connection_snapshot().as_dict()
    except ProviderConnectionError as exc:
        receipt = {
            "kind": "ProviderConnectionHealth", "schema_version": "1.0", "provider_id": provider_id,
            "endpoint_class": "CONFIGURATION", "auth_status": "NOT_EVALUATED", "catalog_status": "NOT_EVALUATED",
            "requested_model": str((profile.get("preferred_models") or [""])[0]), "actual_model": "",
            "structured_output_mode": str(profile.get("structured_output_mode", "")), "structured_output_status": "NOT_EVALUATED",
            "latency_ms": 0, "error_class": exc.error_class, "eligible": False,
            "checked_at": datetime.now(timezone.utc).isoformat(), "credential_present": False,
            "workspace_configured": bool(profile.get("workspace_id")), "probe_steps": [], "contains_credentials": False,
        }
    state = _status(str(receipt.get("error_class", "")), bool(receipt.get("eligible")))
    receipt["status"] = state
    receipt["cost_estimate"] = "UNAVAILABLE"
    receipt["recommended_operator_action"] = {
        "QWEN_INVALID_KEY": "Replace or recreate the Qwen API credential.",
        "QWEN_MISSING_AUTH": "Set CGKN_QWEN_API_KEY or DASHSCOPE_API_KEY for the gateway process.",
        "QWEN_REGION_KEY_MISMATCH": "Match the API key region and Model Studio base URL region.",
        "QWEN_WORKSPACE_UNAUTHORIZED": "Grant the credential access to the configured workspace.",
        "QWEN_WORKSPACE_NOT_FOUND": "Configure a valid Qwen workspace and workspace-specific endpoint.",
        "GROK_INVALID_API_KEY": "Verify or replace the xAI inference API key.",
        "GROK_MISSING_AUTH": "Set CGKN_GROK_API_KEY or XAI_API_KEY for the gateway process.",
        "GROK_WRONG_KEY_TYPE": "Use an xAI inference API key, not a management API key.",
        "DEEPSEEK_MISSING_AUTH": "Set CGKN_DEEPSEEK_API_KEY or DEEPSEEK_API_KEY for the gateway process.",
    }.get(str(receipt.get("error_class", "")), "Review the credential-safe connection profile and sanitized error class.")
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / f"{provider_id}_connection_receipt.json"
    target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return receipt, EXIT_CODES[state]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run independent credential-safe Provider connection diagnostics")
    parser.add_argument("--provider", choices=[*CONNECTOR_TYPES, "all"], required=True)
    parser.add_argument("--output-root", type=pathlib.Path, default=ROOT / "artifacts" / "provider_connections")
    args = parser.parse_args()
    providers = list(CONNECTOR_TYPES) if args.provider == "all" else [args.provider]
    receipts = []; codes = []
    for provider_id in providers:
        receipt, code = diagnose(provider_id, args.output_root.resolve()); receipts.append(receipt); codes.append(code)
    print(json.dumps({"kind": "ProviderConnectionDiagnosticRun", "providers": receipts, "contains_credentials": False}, ensure_ascii=False, indent=2))
    return max(codes, default=0)


if __name__ == "__main__":
    raise SystemExit(main())

