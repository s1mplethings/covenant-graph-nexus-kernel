from __future__ import annotations

import argparse
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
    ProviderProfileCache,
    ProviderSelector,
    SELECTION_POLICY_VERSION,
    aggregate_profiles,
    benchmark_cases,
    suite_hash,
)
from cgkn.providers import CGKNModelRouting, completion_client_from_environment  # noqa: E402


def _write_once(path: pathlib.Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def run(
    routing_path: pathlib.Path,
    output_root: pathlib.Path,
    providers: list[str],
    *,
    actual_models: dict[str, str] | None = None,
    profile_cache: pathlib.Path | None = None,
) -> dict[str, Any]:
    routing = CGKNModelRouting.load(routing_path)
    selected = providers or sorted(routing.allowed_providers)
    if not selected or any(provider not in routing.allowed_providers for provider in selected):
        raise ValueError("benchmark Providers must come from the active routing configuration")
    cases = benchmark_cases()
    actual_models = dict(actual_models or {})
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
                routing.config_hash,
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
        completion_client_from_environment(),
        gateway_config_hash=routing.config_hash,
        source_commit=source_commit,
    )
    output_root.mkdir(parents=True, exist_ok=False)
    receipts = []
    run_id = "provider-benchmark-" + uuid.uuid4().hex[:12]
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
        "benchmark_suite_hash": suite_identity,
        "routing_config_hash": routing.config_hash,
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
    args = parser.parse_args()
    actual_models = {}
    for item in args.actual_model:
        provider, separator, model = item.partition("=")
        if not separator or not provider.strip() or not model.strip():
            parser.error("--actual-model must use provider_id=model_id")
        actual_models[provider.strip()] = model.strip()
    result = run(
        args.routing.resolve(),
        args.output_root.resolve(),
        args.provider,
        actual_models=actual_models,
        profile_cache=args.profile_cache.resolve() if args.profile_cache else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
