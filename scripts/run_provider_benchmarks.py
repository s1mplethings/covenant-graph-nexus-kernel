from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import uuid
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.application.provider_evaluation import (  # noqa: E402
    ProviderEvaluationService,
    ProviderPrice,
    ProviderProfileCache,
    ProviderSelector,
    SELECTION_POLICY_VERSION,
    aggregate_profiles,
    benchmark_cases,
    suite_hash,
)
from cgkn.providers import (  # noqa: E402
    CGKNModelRouting,
    ConnectorCompletionClient,
    DeepSeekConnector,
    GrokConnector,
    ProviderConnectorRegistry,
    QwenConnector,
    completion_client_from_environment,
)


CONNECTOR_TYPES = {
    "qwen": QwenConnector,
    "deepseek": DeepSeekConnector,
    "grok": GrokConnector,
}


def _write_once(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _connector_registry(
    providers: list[str],
    config_root: pathlib.Path,
) -> tuple[ProviderConnectorRegistry, str, dict[str, str], dict[str, str]]:
    connectors = []
    snapshots = []
    actual_models: dict[str, str] = {}
    structured_modes: dict[str, str] = {}
    for provider in providers:
        connector_type = CONNECTOR_TYPES.get(provider)
        if connector_type is None:
            raise ValueError(f"no connector registered for Provider {provider!r}")
        profile_path = config_root / f"{provider}.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        connector = connector_type(profile)
        snapshot = connector.connection_snapshot()
        connectors.append(connector)
        snapshots.append(snapshot.as_dict())
        actual_models[provider] = snapshot.requested_model
        structured_modes[provider] = snapshot.structured_output_mode.value
    encoded = json.dumps(snapshots, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return (
        ProviderConnectorRegistry(connectors),
        "sha256:" + hashlib.sha256(encoded).hexdigest(),
        actual_models,
        structured_modes,
    )


def run(
    routing_path: pathlib.Path,
    output_root: pathlib.Path,
    providers: list[str],
    *,
    actual_models: dict[str, str] | None = None,
    profile_cache: pathlib.Path | None = None,
    transport: str = "gateway",
    connector_config_root: pathlib.Path | None = None,
    prices: dict[str, ProviderPrice] | None = None,
) -> dict[str, Any]:
    routing = CGKNModelRouting.load(routing_path)
    selected = providers or sorted(routing.allowed_providers)
    if not selected or any(provider not in routing.allowed_providers for provider in selected):
        raise ValueError("benchmark Providers must come from the active routing configuration")
    actual_models = dict(actual_models or {})
    run_id = "provider-benchmark-" + uuid.uuid4().hex[:12]
    structured_modes: dict[str, str] = {}
    if transport == "connectors":
        config_root = connector_config_root or ROOT / "config/provider_connections"
        registry, transport_hash, configured_models, structured_modes = _connector_registry(selected, config_root)
        for provider, model in configured_models.items():
            actual_models.setdefault(provider, model)
        client = ConnectorCompletionClient(
            registry,
            enforce_budget=True,
            budget_purpose="BENCHMARK",
            run_id=run_id,
            case_id="provider-evaluation",
        )
    elif transport == "gateway":
        transport_hash = routing.config_hash
        client = completion_client_from_environment()
    else:
        raise ValueError("transport must be gateway or connectors")
    cases = benchmark_cases()
    suite_identity = suite_hash(cases)
    cached_profiles = ProviderProfileCache(profile_cache).load() if profile_cache else ()
    reused_profiles = []
    tasks_to_run: dict[str, set[str]] = {}
    for provider in selected:
        pending = set()
        for task_class in {case.task_class for case in cases}:
            key = (
                provider,
                actual_models.get(provider, "UNAVAILABLE"),
                transport_hash,
                suite_identity,
                task_class,
                SELECTION_POLICY_VERSION,
            )
            cached = next((profile for profile in cached_profiles if profile.cache_key == key), None)
            if cached:
                reused_profiles.append(cached)
            else:
                pending.add(task_class)
        tasks_to_run[provider] = pending
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    service = ProviderEvaluationService(
        client,
        gateway_config_hash=transport_hash,
        source_commit=source_commit,
        prices=prices,
        structured_output_modes=structured_modes,
    )
    output_root.mkdir(parents=True, exist_ok=False)
    receipts = []
    for provider in selected:
        pending_cases = [case for case in cases if case.task_class in tasks_to_run[provider]]
        for receipt in service.run_provider(
            provider,
            run_id=run_id,
            actual_model_hint=actual_models.get(provider, "UNAVAILABLE"),
            cases=pending_cases,
        ):
            service.write_receipt_once(receipt, output_root / "receipts" / provider / f"{receipt.benchmark_id}.json")
            receipts.append(receipt)
    profiles = tuple(reused_profiles) + aggregate_profiles(receipts, benchmark_suite_hash=suite_identity)
    ProviderProfileCache(output_root / "provider_capability_profiles.json").write(profiles)
    selector = ProviderSelector(profiles)
    decisions = []
    missing = []
    for task_class in ("agent.composition", "worker.codegen", "worker.repair"):
        try:
            decision = selector.select(task_class)
        except RuntimeError:
            missing.append(task_class)
        else:
            decisions.append(decision)
            if len(decision.eligible_providers) < 2:
                missing.append(task_class)
    status = "COMPLETE" if not missing else (
        "PROVIDER_SELECTION_BLOCKED_ENVIRONMENT" if len(selected) < 2 else "PROVIDER_SELECTION_NEEDS_REWORK"
    )
    result = {
        "kind": "CGKNProviderSelectionStatus",
        "schema_version": "1.0",
        "status": status,
        "run_id": run_id,
        "providers": selected,
        "transport": transport,
        "actual_models": actual_models,
        "benchmark_suite_hash": suite_identity,
        "routing_config_hash": transport_hash,
        "decisions": [decision.as_dict() for decision in decisions],
        "missing_task_classes": missing,
        "capability_build": "NOT_EVALUATED",
        "live_benchmark_calls": len(receipts),
        "reused_profile_count": len(reused_profiles),
        "fallback": "deny",
        "contains_credentials": False,
    }
    _write_once(output_root / "provider_selection_status.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the bounded, task-specific Provider micro benchmark suite")
    parser.add_argument("--routing", type=pathlib.Path, default=ROOT / "config/provider_profiles/gateway_model_routing.json")
    parser.add_argument("--output-root", type=pathlib.Path, required=True)
    parser.add_argument("--provider", action="append", default=[])
    parser.add_argument("--actual-model", action="append", default=[], help="non-secret provider_id=model_id metadata")
    parser.add_argument("--profile-cache", type=pathlib.Path)
    parser.add_argument("--transport", choices=("gateway", "connectors"), default="gateway")
    parser.add_argument("--connector-config-root", type=pathlib.Path, default=ROOT / "config/provider_connections")
    parser.add_argument(
        "--price",
        action="append",
        default=[],
        help="provider_id=input_per_million,output_per_million; omit to record UNAVAILABLE",
    )
    args = parser.parse_args()
    actual_models = {}
    for item in args.actual_model:
        provider, separator, model = item.partition("=")
        if not separator or not provider.strip() or not model.strip():
            parser.error("--actual-model must use provider_id=model_id")
        actual_models[provider.strip()] = model.strip()
    prices = {}
    for item in args.price:
        provider, separator, rates = item.partition("=")
        input_rate, comma, output_rate = rates.partition(",")
        if not separator or not comma or not provider.strip():
            parser.error("--price must use provider_id=input_per_million,output_per_million")
        prices[provider.strip()] = ProviderPrice(float(input_rate), float(output_rate))
    result = run(
        args.routing.resolve(),
        args.output_root.resolve(),
        args.provider,
        actual_models=actual_models,
        profile_cache=args.profile_cache.resolve() if args.profile_cache else None,
        transport=args.transport,
        connector_config_root=args.connector_config_root.resolve(),
        prices=prices,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
