#!/usr/bin/env python3
"""Run the release evaluation through the frozen API Lab loopback boundary.

The API Lab implementation remains outside this repository.  Its ephemeral
gateway token is passed only through the child environment and is never
printed or written to an evidence artifact.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[1]
API_LAB_COMMIT = "999dff096afe45f058fe67016aee28a73912d5d4"
MODEL_PRICES_USD_PER_MILLION = {
    # Official list prices captured 2026-10-25. DeepSeek uses the higher
    # cache-miss peak rate so the run-level bound cannot understate cost.
    "deepseek": {"input": 0.30, "output": 1.20},
    "qwen": {"input": 1.65, "output": 4.951},
}


def _head(root: pathlib.Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True, encoding="utf-8",
        errors="replace", capture_output=True, check=True,
    )
    return completed.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch the frozen API Lab gateway for one release evaluation")
    parser.add_argument("--api-lab-root", type=pathlib.Path, required=True)
    parser.add_argument("--ledger-root", type=pathlib.Path, required=True)
    parser.add_argument("evaluation_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    lab = args.api_lab_root.resolve()
    if _head(lab) != API_LAB_COMMIT:
        parser.error(f"API Lab must be frozen at {API_LAB_COMMIT}")
    evaluation_args = list(args.evaluation_args)
    if evaluation_args and evaluation_args[0] == "--":
        evaluation_args.pop(0)
    if not evaluation_args or evaluation_args[0] != "--profile":
        parser.error("evaluation arguments must begin with --profile")
    baseline = evaluation_args[evaluation_args.index("--baseline") + 1] if "--baseline" in evaluation_args else "B4_OPTIMIZED_CGNK_RC"
    provider_id = "qwen" if baseline == "B1_DIRECT_STRONG" else "deepseek"
    prices = MODEL_PRICES_USD_PER_MILLION[provider_id]
    task_limit = int(evaluation_args[evaluation_args.index("--limit") + 1]) if "--limit" in evaluation_args else 72
    ledger_root = args.ledger_root.resolve()
    ledger_root.mkdir(parents=True, exist_ok=True)
    ledger = ledger_root / f"{baseline.casefold()}-{uuid.uuid4().hex[:10]}.json"
    sys.path.insert(0, str(lab / "src"))
    from cgkn_provider_lab.gateway import GatewayApplication, GatewayServer
    from cgkn_provider_lab.secrets import SecretManager
    from cgkn_provider_lab.storage import ProviderConfigStore

    server = GatewayServer(GatewayApplication(
        ProviderConfigStore().load_or_create_defaults(), secrets=SecretManager.create_default(),
    ))
    info = server.start()
    environment = dict(os.environ)
    environment.update({
        "CGKN_PROVIDER_GATEWAY_ENABLED": "1",
        "CGKN_PROVIDER_GATEWAY_BASE_URL": info.base_url,
        "CGKN_PROVIDER_GATEWAY_TOKEN": info.access_token,
        "CGKN_PROVIDER_GATEWAY_API_METHOD": "responses",
        "CGKN_PROVIDER_CACHE_MODE": "off",
        "CGKN_PROVIDER_BUDGET_LEDGER": str(ledger),
        "CGKN_PROVIDER_MAX_API_CALLS": str(task_limit),
        "CGKN_PROVIDER_MAX_BENCHMARK_CALLS": str(task_limit),
        "CGKN_PROVIDER_MAX_INPUT_TOKENS": str(task_limit * 15000),
        "CGKN_PROVIDER_MAX_OUTPUT_TOKENS": str(task_limit * 300),
        "CGKN_PROVIDER_MAX_ESTIMATED_COST": "5.0",
        "CGKN_PROVIDER_INPUT_COST_PER_MILLION": str(prices["input"]),
        "CGKN_PROVIDER_OUTPUT_COST_PER_MILLION": str(prices["output"]),
        "CGKN_PROVIDER_CALL_PHASE": "BENCHMARK",
    })
    try:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_cgnk_evaluation.py"), *evaluation_args],
            cwd=ROOT, env=environment, shell=False, check=False,
        )
        return int(completed.returncode)
    finally:
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
