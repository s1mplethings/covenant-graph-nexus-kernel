#!/usr/bin/env python3
"""Run the resumable ITER-060 Project Complexity Frontier evaluation."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Any, Mapping


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cgkn.providers import CGKNModelRouting, GatewayCompletionClient, ModelRoleConfig, completion_client_from_environment
from experiments.release_060.contracts import ArchitectureBaseline, EvaluationPolicy, canonical_hash
from experiments.release_060.leakage import check_family_leakage
from experiments.release_060.runner import SYSTEM_PROMPT, file_bundle_schema, run_family
from experiments.release_060.specs import development_families, formal_families, full_manifest


API_LAB_COMMIT = "7c15f2546ec007cc7e601fa62ae4d88b9ba12f80"
BASELINES = tuple(item.value for item in ArchitectureBaseline)
PRICES_USD_PER_MILLION = {"input": 0.30, "output": 1.20}


def _write(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _git(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=True)
    return completed.stdout.strip()


def _lab_git(root: pathlib.Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=root, text=True, encoding="utf-8", errors="replace", capture_output=True, check=True)
    return completed.stdout.strip()


@contextlib.contextmanager
def managed_gateway(api_lab_root: pathlib.Path | None, ledger_root: pathlib.Path, call_limit: int):
    if api_lab_root is None:
        yield; return
    lab = api_lab_root.resolve()
    if _lab_git(lab, "rev-parse", "HEAD") != API_LAB_COMMIT or _lab_git(lab, "status", "--short"):
        raise RuntimeError(f"API Lab must be clean and frozen at {API_LAB_COMMIT}")
    sys.path.insert(0, str(lab / "src"))
    from cgkn_provider_lab.gateway import GatewayApplication, GatewayServer
    from cgkn_provider_lab.secrets import SecretManager
    from cgkn_provider_lab.storage import ProviderConfigStore
    server = GatewayServer(GatewayApplication(ProviderConfigStore().load_or_create_defaults(), secrets=SecretManager.create_default()))
    info = server.start(); ledger_root.mkdir(parents=True, exist_ok=True)
    updates = {
        "CGKN_PROVIDER_GATEWAY_ENABLED": "1", "CGKN_PROVIDER_GATEWAY_BASE_URL": info.base_url,
        "CGKN_PROVIDER_GATEWAY_TOKEN": info.access_token, "CGKN_PROVIDER_GATEWAY_API_METHOD": "responses",
        "CGKN_PROVIDER_CACHE_MODE": "off", "CGKN_PROVIDER_BUDGET_LEDGER": str(ledger_root / "provider-budget.json"),
        "CGKN_PROVIDER_MAX_API_CALLS": str(call_limit), "CGKN_PROVIDER_MAX_BENCHMARK_CALLS": str(call_limit),
        "CGKN_PROVIDER_MAX_INPUT_TOKENS": str(call_limit * 40_000), "CGKN_PROVIDER_MAX_OUTPUT_TOKENS": str(call_limit * 6_000),
        "CGKN_PROVIDER_MAX_ESTIMATED_COST": "100.0", "CGKN_PROVIDER_INPUT_COST_PER_MILLION": str(PRICES_USD_PER_MILLION["input"]),
        "CGKN_PROVIDER_OUTPUT_COST_PER_MILLION": str(PRICES_USD_PER_MILLION["output"]), "CGKN_PROVIDER_CALL_PHASE": "BENCHMARK",
    }
    previous = {key: os.environ.get(key) for key in updates}; os.environ.update(updates)
    try:
        yield
    finally:
        server.stop()
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


def live_client(policy: EvaluationPolicy) -> tuple[Any, ModelRoleConfig, dict[str, Any]]:
    client = completion_client_from_environment()
    if not isinstance(client, GatewayCompletionClient):
        raise RuntimeError("reviewed API Lab Gateway route is unavailable")
    routing = CGKNModelRouting.load(ROOT / "config" / "provider_profiles" / "gateway_model_routing.json")
    if routing.worker.model != policy.provider:
        raise RuntimeError("worker route does not match frozen ITER-060 Provider")
    config = ModelRoleConfig(
        "worker", routing.worker.model, timeout_seconds=policy.request_timeout_seconds,
        max_output_tokens=policy.max_output_tokens, temperature=policy.temperature,
        reasoning_effort="none", task_class="release.project_complexity_frontier",
        operation="MATERIALIZE_PROJECT_EPISODE", outer_deadline_seconds=policy.outer_deadline_seconds,
        deadline_reserve_seconds=30, thinking_mode="disabled",
    )
    route = {
        "provider_id": routing.worker.model, "expected_actual_model": policy.model,
        "temperature": config.temperature, "max_output_tokens": config.max_output_tokens,
        "request_timeout_seconds": config.timeout_seconds, "outer_deadline_seconds": config.outer_deadline_seconds,
        "fallback": routing.fallback, "api_lab_commit": API_LAB_COMMIT,
        "selector_authority": "CGKN.StructuredAnswerSelector", "route_mode": "raw_defer",
    }
    route["route_hash"] = canonical_hash(route)
    return client, config, route


def _freeze_document(source_version: str, policy: EvaluationPolicy) -> dict[str, Any]:
    manifest = full_manifest(); formal = formal_families()
    value = {
        "kind": "CGNKITER060FormalFreeze", "schema_version": "1.0", "source_version": source_version,
        "source_tree": _git("rev-parse", f"{source_version}^{{tree}}"),
        "project_spec_hash": manifest["manifest_hash"],
        "formal_family_manifest_hash": canonical_hash([item.public_dict() | {"private_hash": item.private_hash} for item in formal]),
        "baseline_config_hash": canonical_hash(BASELINES), "model_config_hash": canonical_hash({"provider": policy.provider, "model": policy.model, "temperature": policy.temperature}),
        "budget_hash": canonical_hash({"max_calls": policy.max_provider_calls_per_family, "max_repairs": policy.max_repairs_per_episode, "max_output_tokens": policy.max_output_tokens, "timeouts": [policy.request_timeout_seconds, policy.outer_deadline_seconds]}),
        "test_authority_hash": canonical_hash({"public_hashes": [item.public_hash for item in formal], "private_hashes": [item.private_hash for item in formal]}),
        "corpus_policy_hash": canonical_hash({"read": False, "write": True, "all_attempts": True, "split": "FORMAL_HOLDOUT"}),
        "complexity_policy_hash": canonical_hash([item.raw_complexity for item in formal]),
    }
    value["freeze_hash"] = canonical_hash(value)
    return value


def _prepare_freeze(artifact_root: pathlib.Path, source_version: str, policy: EvaluationPolicy, *, formal: bool) -> dict[str, Any]:
    source_slug = "".join(char for char in source_version[:8].casefold() if char.isalnum()) or "unknown"
    path = artifact_root / ("formal-freeze.json" if formal else f"development-freeze-{source_slug}.json")
    expected = _freeze_document(source_version, policy)
    if path.is_file():
        observed = json.loads(path.read_text(encoding="utf-8"))
        if observed != expected:
            raise RuntimeError("existing freeze document does not match source/spec/policy")
    else:
        _write(path, expected)
    return expected


def _preflight(artifact_root: pathlib.Path, policy: EvaluationPolicy, api_lab_root: pathlib.Path | None) -> dict[str, Any]:
    artifact_root.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(artifact_root)
    leakage = check_family_leakage(development_families() + formal_families())
    status = "PASS"
    error = ""
    try:
        with managed_gateway(api_lab_root, artifact_root / "preflight-ledger", 1):
            _, _, route = live_client(policy)
    except Exception as exc:
        route = {}; status = "ENVIRONMENT_BLOCKED"; error = f"{type(exc).__name__}: {str(exc)[:500]}"
    if disk.free < 10 * 1024**3 or leakage["status"] != "PASS": status = "FAIL"
    return {"kind": "CGNKITER060Preflight", "status": status, "free_bytes": disk.free, "required_reserve_bytes": 10 * 1024**3, "leakage": leakage, "route": route, "provider_call_made": False, "error": error}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("manifest", "preflight", "development", "formal", "resume", "summarize"))
    parser.add_argument("--artifact-root", type=pathlib.Path, default=pathlib.Path(r"F:\CGKN-ITER-060"))
    parser.add_argument("--corpus-root", type=pathlib.Path)
    parser.add_argument("--api-lab-root", type=pathlib.Path)
    parser.add_argument("--baseline", action="append", choices=BASELINES)
    parser.add_argument("--limit-families", type=int)
    parser.add_argument("--source-version")
    args = parser.parse_args()
    policy = EvaluationPolicy(); artifact_root = args.artifact_root.resolve()
    if args.command == "manifest":
        print(json.dumps(full_manifest(), ensure_ascii=False, sort_keys=True, indent=2)); return 0
    if args.command == "preflight":
        result = _preflight(artifact_root, policy, args.api_lab_root)
        _write(artifact_root / "preflight.json", result); print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0 if result["status"] == "PASS" else 2
    if args.command == "summarize":
        receipts = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((artifact_root / "runs" / "receipts").glob("*.json"))]
        result = {"attempts": len(receipts), "status_counts": {status: sum(row.get("status") == status for row in receipts) for status in ("PASS", "FAIL", "ABORTED")}, "provider_calls": sum(int(row.get("provider_calls", 0)) for row in receipts), "receipt_hashes": [row.get("receipt_hash") for row in receipts]}
        result["summary_hash"] = canonical_hash(result); print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)); return 0

    formal = args.command == "formal" or args.command == "resume" and (artifact_root / "formal-freeze.json").is_file()
    families = formal_families() if formal else development_families()
    if args.limit_families is not None:
        if args.limit_families < 1: parser.error("--limit-families must be positive")
        families = families[: args.limit_families]
    baselines = tuple(args.baseline or BASELINES)
    source_version = args.source_version or _git("rev-parse", "HEAD")
    if formal:
        if _git("status", "--short"):
            raise RuntimeError("formal evaluation requires a clean frozen source checkout")
        if source_version != _git("rev-parse", "HEAD"):
            raise RuntimeError("formal source version must equal checked-out HEAD")
    freeze = _prepare_freeze(artifact_root, source_version, policy, formal=formal)
    corpus_root = (args.corpus_root or artifact_root / "project-corpus").resolve()
    call_limit = max(1, len(families) * len(baselines) * policy.max_provider_calls_per_family)
    results = []
    with managed_gateway(args.api_lab_root, artifact_root / "provider-ledger", call_limit):
        client, config, route = live_client(policy)
        for family in families:
            for baseline in baselines:
                results.append(run_family(family, baseline, destination=artifact_root / "runs", corpus_root=corpus_root, client=client, config=config, policy=policy, source_version=source_version))
                all_receipts = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((artifact_root / "runs" / "receipts").glob("*.json"))]
                _write(artifact_root / "run-index.json", {"freeze_hash": freeze["freeze_hash"], "route": route, "runs": [{"run_id": row["run_id"], "family_id": row["family_id"], "baseline": row["baseline"], "status": row["status"], "receipt_hash": row["receipt_hash"]} for row in all_receipts]})
    summary = {"attempts": len(results), "passes": sum(row["status"] == "PASS" for row in results), "failures": sum(row["status"] != "PASS" for row in results), "source_version": source_version, "freeze_hash": freeze["freeze_hash"], "route": route}
    summary["summary_hash"] = canonical_hash(summary); _write(artifact_root / ("formal-summary.json" if formal else "development-summary.json"), summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
