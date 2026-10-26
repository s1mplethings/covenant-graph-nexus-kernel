#!/usr/bin/env python3
"""Run or inspect ITER-058 CGNK Essential Workload V1."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import pathlib
import subprocess
import sys
import uuid
from typing import Any, Mapping


ROOT = pathlib.Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "src"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from cgkn.providers import CGKNModelRouting, GatewayCompletionClient, ModelRoleConfig, completion_client_from_environment
from experiments.release_058.analysis import analyze
from experiments.release_058.essential_workload import BASELINES, canonical_hash, development_chains, formal_chains, workload_manifest
from experiments.release_058.runner import ANSWER_SCHEMA, SYSTEM_PROMPT, run_chain, summarize_runs


API_LAB_COMMIT = "7c15f2546ec007cc7e601fa62ae4d88b9ba12f80"
DEEPSEEK_PRICES_USD_PER_MILLION = {"input": 0.30, "output": 1.20}


def _write(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _live_completion() -> tuple[Any, Mapping[str, Any]]:
    base = completion_client_from_environment()
    if not isinstance(base, GatewayCompletionClient):
        raise RuntimeError("reviewed Gateway route unavailable")
    routing = CGKNModelRouting.load(ROOT / "config" / "provider_profiles" / "gateway_model_routing.json")
    config = ModelRoleConfig(
        "worker", routing.worker.model, timeout_seconds=90, max_output_tokens=450,
        temperature=0.0, reasoning_effort="none", task_class="release.essential_workload",
        operation="EVALUATE_CHAIN_EPISODE", outer_deadline_seconds=120,
        deadline_reserve_seconds=30, thinking_mode="disabled",
    )

    def complete(run_id: str, episode_id: str, packet: Mapping[str, Any], _: Mapping[str, Any]):
        client = base.bind_run(f"{run_id}-{episode_id.casefold()}", episode_id, budget_purpose="BENCHMARK")
        return client.complete(
            system=SYSTEM_PROMPT,
            user=json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            schema_name="cgnk_essential_episode_answer",
            schema=ANSWER_SCHEMA,
            config=config,
        )

    return complete, {
        "provider": routing.worker.model, "model": routing.worker.model,
        "temperature": 0.0, "max_output_tokens": 450,
        "timeout_seconds": 90, "outer_deadline_seconds": 120,
        "logical_retries": 0, "schema_hash": canonical_hash(ANSWER_SCHEMA),
        "system_prompt_hash": canonical_hash(SYSTEM_PROMPT),
    }


def _load_runs(path: pathlib.Path) -> list[dict[str, Any]]:
    index = json.loads(path.read_text(encoding="utf-8"))
    return [dict(row) for row in index.get("runs", ())]


def _git_output(root: pathlib.Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=root, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=True,
    )
    return completed.stdout.strip()


@contextlib.contextmanager
def _managed_gateway(api_lab_root: pathlib.Path | None, ledger_root: pathlib.Path, call_limit: int):
    """Start the frozen API Lab boundary without persisting its ephemeral token."""
    if api_lab_root is None:
        yield
        return
    lab = api_lab_root.resolve()
    if _git_output(lab, "rev-parse", "HEAD") != API_LAB_COMMIT:
        raise RuntimeError(f"API Lab must be frozen at {API_LAB_COMMIT}")
    sys.path.insert(0, str(lab / "src"))
    from cgkn_provider_lab.gateway import GatewayApplication, GatewayServer
    from cgkn_provider_lab.secrets import SecretManager
    from cgkn_provider_lab.storage import ProviderConfigStore

    server = GatewayServer(GatewayApplication(
        ProviderConfigStore().load_or_create_defaults(), secrets=SecretManager.create_default(),
    ))
    info = server.start()
    ledger_root.mkdir(parents=True, exist_ok=True)
    ledger = ledger_root / "provider-budget.json"
    updates = {
        "CGKN_PROVIDER_GATEWAY_ENABLED": "1",
        "CGKN_PROVIDER_GATEWAY_BASE_URL": info.base_url,
        "CGKN_PROVIDER_GATEWAY_TOKEN": info.access_token,
        "CGKN_PROVIDER_GATEWAY_API_METHOD": "responses",
        "CGKN_PROVIDER_CACHE_MODE": "off",
        "CGKN_PROVIDER_BUDGET_LEDGER": str(ledger),
        "CGKN_PROVIDER_MAX_API_CALLS": str(call_limit),
        "CGKN_PROVIDER_MAX_BENCHMARK_CALLS": str(call_limit),
        "CGKN_PROVIDER_MAX_INPUT_TOKENS": str(call_limit * 15_000),
        "CGKN_PROVIDER_MAX_OUTPUT_TOKENS": str(call_limit * 450),
        "CGKN_PROVIDER_MAX_ESTIMATED_COST": "5.0",
        "CGKN_PROVIDER_INPUT_COST_PER_MILLION": str(DEEPSEEK_PRICES_USD_PER_MILLION["input"]),
        "CGKN_PROVIDER_OUTPUT_COST_PER_MILLION": str(DEEPSEEK_PRICES_USD_PER_MILLION["output"]),
        "CGKN_PROVIDER_CALL_PHASE": "BENCHMARK",
    }
    previous = {key: os.environ.get(key) for key in updates}
    os.environ.update(updates)
    try:
        yield
    finally:
        server.stop()
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("manifest", "preflight", "development", "formal", "analyze"))
    parser.add_argument("--artifact-root", type=pathlib.Path, default=ROOT / ".service_scratch" / "release-058")
    parser.add_argument("--baseline", action="append", choices=BASELINES)
    parser.add_argument("--limit-chains", type=int)
    parser.add_argument("--index", type=pathlib.Path)
    parser.add_argument("--api-lab-root", type=pathlib.Path)
    args = parser.parse_args()

    if args.command == "manifest":
        result = workload_manifest()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "preflight":
        try:
            with _managed_gateway(args.api_lab_root, args.artifact_root / "preflight-ledger", 1):
                _, config = _live_completion()
                result = {
                    "status": "PASS", "route": config, "provider_call_made": False,
                    "api_lab_commit": API_LAB_COMMIT,
                }
        except Exception as exc:
            result = {"status": "ENVIRONMENT_BLOCKED", "error_type": type(exc).__name__, "error": str(exc)[:500], "provider_call_made": False}
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 2
    if args.command == "analyze":
        if args.index is None:
            parser.error("analyze requires --index")
        result = analyze(_load_runs(args.index.resolve()))
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    chains = development_chains() if args.command == "development" else formal_chains()
    if args.limit_chains is not None:
        if args.limit_chains <= 0:
            parser.error("--limit-chains must be positive")
        chains = chains[:args.limit_chains]
    baselines = tuple(args.baseline or BASELINES)
    batch = f"{args.command}-{canonical_hash([row.scenario_id for row in chains] + list(baselines))[7:15]}-{uuid.uuid4().hex[:8]}"
    destination = args.artifact_root.resolve() / batch
    destination.mkdir(parents=True, exist_ok=False)
    runs: list[dict[str, Any]] = []
    call_limit = max(1, len(chains) * len(baselines) * 5)
    with _managed_gateway(args.api_lab_root, destination / "provider-ledger", call_limit):
        complete, model_config = _live_completion()
        for chain in chains:
            for baseline in baselines:
                run = run_chain(chain, baseline, destination / "workspaces", complete, model_config=model_config)
                runs.append(run)
                _write(destination / "runs" / f"{run['run_id']}.json", run)
    source_revision = _git_output(ROOT, "rev-parse", "HEAD")
    dirty = bool(_git_output(ROOT, "status", "--short"))
    result = {
        "kind": "CGNKEssentialWorkloadRunIndex", "schema_version": "1.0",
        "batch_id": batch, "split": args.command, "source_revision": source_revision,
        "source_dirty": dirty, "api_lab_commit": API_LAB_COMMIT,
        "workload_manifest_hash": workload_manifest()["manifest_hash"],
        "model_config": model_config, "model_config_hash": canonical_hash(model_config),
        "baseline_config_hash": canonical_hash({"baselines": baselines, "system": SYSTEM_PROMPT}),
        "runs": runs, "summary": summarize_runs(runs),
    }
    _write(destination / "index.json", result)
    print(json.dumps({"artifact": str(destination / "index.json"), "summary": result["summary"]}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
